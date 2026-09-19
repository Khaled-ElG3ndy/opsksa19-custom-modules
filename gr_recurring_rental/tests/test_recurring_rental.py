# -*- coding: utf-8 -*-
"""Recurring rentals: remind, prepare a draft, and commit to nothing.

The rules these tests defend, in order of importance:

  * a prepared order is a DRAFT and stays one;
  * no validation is bypassed by preparing from a template - contract
    approval, availability, double-booking and the third-party supplier
    window all still apply;
  * an occurrence is handled exactly once;
  * a date that passes unhandled goes Overdue and is never advanced quietly.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestRecurringRental(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Recurring = cls.env['gr.recurring.rental']
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.Activity = cls.env['mail.activity']

        cls.customer = cls.env['res.partner'].create({'name': 'Recurring Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Recurring Site', 'partner_id': cls.customer.id})
        cls.responsible = cls.env['res.users'].create({
            'name': 'Recurring Officer', 'login': 'recurring_officer',
            'email': 'recurring_officer@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'gr_security_base.group_generator_general_manager').id),
            ]})
        cls.gm = cls.responsible

        cls.generator_type = cls.env.ref('gr_equipment.equipment_type_generator')
        cls.generator = cls.Asset.create({
            'name': 'REC-GEN-500', 'pm_interval_hours': 2000.0,
            'owner_type': 'owned', 'kva_rating': 500.0,
            'equipment_type_id': cls.generator_type.id})
        cls.contract = cls._create_contract()

    @classmethod
    def _create_contract(cls, state='active'):
        contract = cls.env['gr.rental.contract'].create({
            'partner_id': cls.customer.id, 'site_id': cls.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 800.0})
        if state != 'draft':
            contract.action_submit()
            contract.with_user(cls.gm).action_approve()
            if state == 'active':
                contract.action_activate()
        return contract

    def _recurring(self, **kw):
        vals = {
            'partner_id': self.customer.id,
            'site_id': self.site.id,
            'contract_id': self.contract.id,
            'user_id': self.responsible.id,
            'frequency': 'monthly',
            'interval': 1,
            'next_rental_date': date(2026, 9, 20),
            'reminder_days_before': 2,
            'rental_duration_days': 10,
        }
        vals.update(kw)
        recurring = self.Recurring.create(vals)
        if 'line_ids' not in kw:
            self.env['gr.recurring.rental.line'].create({
                'recurring_id': recurring.id,
                'equipment_type_id': self.generator_type.id,
                'required_kva': 500.0,
                'quantity': 1,
            })
        return recurring

    # ------------------------------------------------------------------
    # Test 1 - monthly recurrence advances correctly
    # ------------------------------------------------------------------
    def test_01_monthly_recurrence_advances(self):
        rec = self._recurring()
        self.assertEqual(rec.next_rental_date, date(2026, 9, 20))
        self.assertEqual(rec.day_of_month, 20)
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 10, 20))
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 11, 20))

    def test_01b_every_two_months(self):
        rec = self._recurring(interval=2)
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 11, 20))

    def test_01c_weekly(self):
        rec = self._recurring(frequency='weekly', interval=2)
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 10, 4))

    # ------------------------------------------------------------------
    # Test 2 - the reminder fires once, however often the cron runs
    # ------------------------------------------------------------------
    def test_02_reminder_is_raised_once(self):
        rec = self._recurring(next_rental_date=date.today() + timedelta(days=2))
        self.assertEqual(rec.next_reminder_date, date.today())

        def reminders():
            return self.Activity.search([
                ('res_model', '=', 'gr.recurring.rental'),
                ('res_id', '=', rec.id)])

        self.assertFalse(reminders())
        self.Recurring._cron_recurring_rental_reminders()
        activities = reminders()
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, self.responsible)
        self.assertEqual(activities.date_deadline, rec.next_rental_date)
        self.assertIn(self.customer.name, activities.note)
        # Running it again - same day or any later day - changes nothing.
        self.Recurring._cron_recurring_rental_reminders()
        self.Recurring._cron_recurring_rental_reminders()
        self.assertEqual(len(reminders()), 1)

    def test_02b_no_reminder_before_the_lead_time(self):
        rec = self._recurring(next_rental_date=date.today() + timedelta(days=10))
        self.Recurring._cron_recurring_rental_reminders()
        self.assertFalse(self.Activity.search([
            ('res_model', '=', 'gr.recurring.rental'), ('res_id', '=', rec.id)]))

    # ------------------------------------------------------------------
    # Test 3 - the lead time is per arrangement
    # ------------------------------------------------------------------
    def test_03_lead_time_is_per_arrangement(self):
        five = self._recurring(
            next_rental_date=date.today() + timedelta(days=5),
            reminder_days_before=5)
        two = self._recurring(
            next_rental_date=date.today() + timedelta(days=5),
            reminder_days_before=2)
        self.assertEqual(five.next_reminder_date, date.today())
        self.assertEqual(two.next_reminder_date,
                         date.today() + timedelta(days=3))
        self.Recurring._cron_recurring_rental_reminders()

        def count(rec):
            return self.Activity.search_count([
                ('res_model', '=', 'gr.recurring.rental'), ('res_id', '=', rec.id)])

        self.assertEqual(count(five), 1, "5-day lead time should fire today")
        self.assertEqual(count(two), 0, "2-day lead time should not fire yet")

    # ------------------------------------------------------------------
    # Test 4 - what comes out is a draft, and only a draft
    # ------------------------------------------------------------------
    def test_04_prepared_order_is_draft_only(self):
        rec = self._recurring()
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.partner_id, self.customer)
        self.assertEqual(order.site_id, self.site)
        self.assertEqual(order.contract_id, self.contract)
        self.assertEqual(order.recurring_rental_id, rec)
        self.assertEqual(
            fields.Datetime.to_datetime(order.planned_dispatch_datetime).date(),
            date(2026, 9, 20))
        self.assertEqual(
            fields.Datetime.to_datetime(order.planned_return_datetime).date(),
            date(2026, 9, 30), "duration of 10 days sets the planned return")
        # Nothing was committed on the way out.
        self.assertFalse(order.actual_dispatch_datetime)
        self.assertEqual(rec.last_order_id, order)
        self.assertEqual(rec.order_count, 1)
        self.assertEqual(order.approval_state, 'pending',
                         "no approval document is generated automatically")

    def test_04b_recurring_items_become_order_lines(self):
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'required_kva': 500.0, 'quantity': 1,
        }), (0, 0, {
            'equipment_type_id': self.env.ref('gr_equipment.equipment_type_cable').id,
            'quantity': 2,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        # Quantity 2 becomes two lines: each line is one physical serial.
        self.assertEqual(len(order.item_line_ids), 3)
        self.assertEqual(set(order.item_line_ids.mapped('quantity_days')), {10.0})

    # ------------------------------------------------------------------
    # Test 5 - an occurrence is prepared exactly once
    # ------------------------------------------------------------------
    def test_05_same_occurrence_cannot_be_prepared_twice(self):
        rec = self._recurring()
        rec.action_prepare_next_rental()
        self.assertEqual(self.Order.search_count(
            [('recurring_rental_id', '=', rec.id)]), 1)
        # Roll the date back to the occurrence just handled and try again.
        rec.next_rental_date = date(2026, 9, 20)
        with self.assertRaises(UserError) as caught:
            rec.action_prepare_next_rental()
        self.assertIn('already been prepared', str(caught.exception))
        self.assertEqual(self.Order.search_count(
            [('recurring_rental_id', '=', rec.id)]), 1)

    def test_05b_cancelled_order_frees_the_occurrence(self):
        """A draft that was cancelled should not block the month for ever."""
        rec = self._recurring()
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        order.action_cancel()
        rec.next_rental_date = date(2026, 9, 20)
        rec.action_prepare_next_rental()
        self.assertEqual(self.Order.search_count(
            [('recurring_rental_id', '=', rec.id), ('state', '!=', 'cancelled')]), 1)

    # ------------------------------------------------------------------
    # Test 6 - skipping a month
    # ------------------------------------------------------------------
    def test_06_skip_occurrence(self):
        rec = self._recurring()
        rec.action_skip_occurrence()
        self.assertEqual(self.Order.search_count(
            [('recurring_rental_id', '=', rec.id)]), 0)
        self.assertEqual(rec.next_rental_date, date(2026, 10, 20))
        self.assertTrue(rec.active, "skipping must not pause the arrangement")
        skipped = rec.occurrence_ids.filtered(
            lambda o: o.occurrence_date == date(2026, 9, 20))
        self.assertEqual(skipped.state, 'skipped')
        bodies = ' '.join(rec.message_ids.mapped('body'))
        self.assertIn('skipped', bodies.lower())

    # ------------------------------------------------------------------
    # Test 7 - an unhandled date goes overdue and stays put
    # ------------------------------------------------------------------
    def test_07_overdue_is_never_advanced_silently(self):
        rec = self._recurring(next_rental_date=date.today() - timedelta(days=2))
        self.assertEqual(rec.occurrence_state, 'overdue')
        due = rec.next_rental_date
        self.Recurring._cron_recurring_rental_reminders()
        self.assertEqual(rec.next_rental_date, due,
                         "the cron must never move an occurrence date")
        self.assertEqual(rec.occurrence_state, 'overdue')
        # It still nags, because somebody has to deal with it.
        self.assertEqual(self.Activity.search_count([
            ('res_model', '=', 'gr.recurring.rental'), ('res_id', '=', rec.id)]), 1)

    def test_07b_states_across_the_window(self):
        today = date.today()
        self.assertEqual(
            self._recurring(next_rental_date=today + timedelta(days=30)).occurrence_state,
            'scheduled')
        self.assertEqual(
            self._recurring(next_rental_date=today + timedelta(days=1)).occurrence_state,
            'due_soon')
        self.assertEqual(
            self._recurring(next_rental_date=today).occurrence_state, 'due_today')

    # ------------------------------------------------------------------
    # Test 8 - a paused arrangement is left alone
    # ------------------------------------------------------------------
    def test_08_archived_is_ignored_by_the_cron(self):
        rec = self._recurring(next_rental_date=date.today())
        rec.active = False
        self.Recurring._cron_recurring_rental_reminders()
        self.assertFalse(self.Activity.search([
            ('res_model', '=', 'gr.recurring.rental'), ('res_id', '=', rec.id)]))
        with self.assertRaises(UserError):
            rec.action_prepare_next_rental()
        # History survives, and it can come back.
        rec.active = True
        self.Recurring._cron_recurring_rental_reminders()
        self.assertEqual(self.Activity.search_count([
            ('res_model', '=', 'gr.recurring.rental'), ('res_id', '=', rec.id)]), 1)

    # ------------------------------------------------------------------
    # Test 9 - a preferred unit that is not free is not forced on
    # ------------------------------------------------------------------
    def test_09_unavailable_preferred_asset_is_left_off(self):
        self.generator.status = 'under_maintenance'
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': self.generator.id,
            'required_kva': 500.0, 'quantity': 1,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertEqual(len(order.item_line_ids), 1)
        self.assertFalse(order.item_line_ids.equipment_asset_id,
                         "an unavailable unit must not be pre-filled")
        self.assertFalse(order.asset_id)
        bodies = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('need a physical unit selected', bodies)

    def test_09b_available_preferred_asset_is_used(self):
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': self.generator.id,
            'required_kva': 500.0, 'quantity': 1,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertEqual(order.item_line_ids.equipment_asset_id, self.generator)
        self.assertEqual(order.asset_id, self.generator,
                         "the primary asset syncs from the line as usual")

    def test_09c_customer_owned_preferred_asset_is_refused(self):
        owner = self.env['res.partner'].create({'name': 'Owning Customer'})
        serviced = self.Asset.create({
            'name': 'REC-CUSTOMER-OWNED', 'owner_type': 'customer_owned',
            'owner_partner_id': owner.id,
            'equipment_type_id': self.generator_type.id})
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': serviced.id, 'quantity': 1,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertFalse(order.item_line_ids.equipment_asset_id)

    # ------------------------------------------------------------------
    # Tests 10 & 11 - third-party rules survive intact
    # ------------------------------------------------------------------
    def _third_party_asset(self, date_start, date_end):
        supplier = self.env['res.partner'].create({'name': 'Recurring Supplier'})
        asset = self.Asset.create({
            'name': 'REC-EXT-500', 'pm_interval_hours': 2000.0,
            'owner_type': 'rented_in', 'owner_partner_id': supplier.id,
            'kva_rating': 500.0, 'equipment_type_id': self.generator_type.id})
        service = self.env['product.product'].create({
            'name': 'Recurring Rent-in', 'type': 'service', 'purchase_ok': True})
        self.env['gr.sublet.agreement'].create({
            'asset_id': asset.id, 'vendor_id': supplier.id,
            'rent_in_product_id': service.id, 'rent_in_amount': 5000.0,
            'date_start': date_start, 'date_end': date_end})
        asset.invalidate_recordset()
        return asset

    def test_10_third_party_outside_supplier_window_is_not_prefilled(self):
        # Supplier window ends before the customer rental would end.
        asset = self._third_party_asset(date(2026, 9, 1), date(2026, 9, 25))
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': asset.id, 'quantity': 1,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertFalse(order.item_line_ids.equipment_asset_id,
                         "supplier-window validation must not be bypassed")
        bodies = ' '.join(order.message_ids.mapped('body'))
        self.assertIn('supplier return date', bodies)
        # And the hard rule still bites if someone attaches it by hand.
        with self.assertRaises(ValidationError):
            order.item_line_ids.equipment_asset_id = asset.id

    def test_10b_expired_supplier_rental_is_not_prefilled(self):
        asset = self._third_party_asset(
            date.today() - timedelta(days=60), date.today() - timedelta(days=30))
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': asset.id, 'quantity': 1,
        })])
        self.assertEqual(asset.supplier_rental_status, 'expired')
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertFalse(order.item_line_ids.equipment_asset_id)

    def test_11_third_party_inside_window_prepares_and_computes_buffer(self):
        asset = self._third_party_asset(date(2026, 9, 1), date(2026, 10, 15))
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': asset.id, 'quantity': 1,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertEqual(order.item_line_ids.equipment_asset_id, asset)
        self.assertEqual(order.asset_id, asset)
        self.assertTrue(order.sublet_agreement_id,
                        "the supplier agreement auto-links as usual")
        # Customer returns 30/09, supplier due back 15/10 -> 15 days, calm.
        self.assertEqual(order.supplier_return_buffer_days, 15)
        self.assertEqual(order.supplier_buffer_level, 'ok')

    def test_11b_tight_supplier_buffer_still_warns_on_a_prepared_order(self):
        asset = self._third_party_asset(date(2026, 9, 1), date(2026, 10, 2))
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': asset.id, 'quantity': 1,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        self.assertEqual(order.supplier_return_buffer_days, 2)
        self.assertEqual(order.supplier_buffer_level, 'critical')
        self.assertTrue(order.supplier_buffer_message)

    # ------------------------------------------------------------------
    # Test 12 - an unusable contract stops preparation
    # ------------------------------------------------------------------
    def test_12_inactive_contract_blocks_preparation(self):
        draft_contract = self._create_contract(state='draft')
        rec = self._recurring(contract_id=draft_contract.id)
        with self.assertRaises(UserError) as caught:
            rec.action_prepare_next_rental()
        self.assertIn('not active', str(caught.exception))
        self.assertEqual(self.Order.search_count(
            [('recurring_rental_id', '=', rec.id)]), 0)

    def test_12b_missing_contract_blocks_preparation(self):
        rec = self._recurring(contract_id=False)
        with self.assertRaises(UserError):
            rec.action_prepare_next_rental()

    # ------------------------------------------------------------------
    # Test 13 - month lengths
    # ------------------------------------------------------------------
    def test_13_end_of_month_anchoring(self):
        rec = self._recurring(next_rental_date=date(2026, 1, 31))
        self.assertEqual(rec.day_of_month, 31)
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 2, 28),
                         "February uses its last valid day")
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 3, 31),
                         "and March returns to the anchor day")
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2026, 4, 30))

    def test_13b_leap_year(self):
        rec = self._recurring(next_rental_date=date(2028, 1, 31))
        rec.action_prepare_next_rental()
        self.assertEqual(rec.next_rental_date, date(2028, 2, 29))

    # ------------------------------------------------------------------
    # Test 14 - reminders do not outlive their occurrence
    # ------------------------------------------------------------------
    def _reminders(self, rec):
        return self.Activity.search([
            ('res_model', '=', 'gr.recurring.rental'), ('res_id', '=', rec.id)])

    def test_14_preparing_closes_the_reminder(self):
        rec = self._recurring(next_rental_date=date.today() + timedelta(days=1))
        self.Recurring._cron_recurring_rental_reminders()
        self.assertEqual(len(self._reminders(rec)), 1)
        rec.action_prepare_next_rental()
        self.assertFalse(self._reminders(rec),
                         "the reminder must not survive the work being done")

    def test_14b_skipping_closes_the_reminder(self):
        rec = self._recurring(next_rental_date=date.today() + timedelta(days=1))
        self.Recurring._cron_recurring_rental_reminders()
        self.assertEqual(len(self._reminders(rec)), 1)
        rec.action_skip_occurrence()
        self.assertFalse(self._reminders(rec))

    # ------------------------------------------------------------------
    # Customer-facing plumbing
    # ------------------------------------------------------------------
    def test_partner_smart_button_counts_active_arrangements(self):
        self.assertEqual(self.customer.recurring_rental_count, 0)
        first = self._recurring()
        second = self._recurring(next_rental_date=date(2026, 9, 25))
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.recurring_rental_count, 2,
                         "a customer may have several arrangements")
        second.active = False
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.recurring_rental_count, 1)
        action = self.customer.action_view_recurring_rentals()
        self.assertEqual(action['res_model'], 'gr.recurring.rental')
        self.assertIn(first, self.Recurring.search(action['domain']))

    def test_partner_alert_reflects_the_worst_arrangement(self):
        self._recurring(next_rental_date=date.today())
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.recurring_rental_alert, 'due_today')
        self._recurring(next_rental_date=date.today() - timedelta(days=1))
        self.customer.invalidate_recordset()
        self.assertEqual(self.customer.recurring_rental_alert, 'overdue')

    def test_pricing_uses_current_catalogue_unless_overridden(self):
        self.generator.rental_daily_rate = 900.0
        rec = self._recurring(line_ids=[(0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': self.generator.id, 'quantity': 1,
        }), (0, 0, {
            'equipment_type_id': self.generator_type.id,
            'preferred_asset_id': False, 'quantity': 1,
            'daily_rate_override': 111.0,
        })])
        action = rec.action_prepare_next_rental()
        order = self.Order.browse(action['res_id'])
        rates = order.item_line_ids.mapped('daily_rate')
        self.assertIn(900.0, rates, "an empty rate prices from the asset today")
        self.assertIn(111.0, rates, "an agreed rate is copied as an override")

    def test_occurrence_log_is_unique_per_date(self):
        rec = self._recurring()
        rec.action_skip_occurrence()
        # The unique constraint is the real duplicate guard, so prove it at the
        # database level. A savepoint keeps the poisoned transaction contained.
        with self.assertRaises(Exception), self.env.cr.savepoint():
            self.env['gr.recurring.rental.occurrence'].create({
                'recurring_id': rec.id,
                'occurrence_date': date(2026, 9, 20),
                'state': 'prepared',
            })
            self.env.flush_all()
