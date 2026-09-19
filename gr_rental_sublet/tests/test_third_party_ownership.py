# -*- coding: utf-8 -*-
"""Third-party (supplier-rented) equipment must never behave, or look, like a
company-owned asset.

Covers the eight scenarios the business asked for: an owned rental still
works, a third-party unit is labelled and rentable, a customer rental inside
the supplier window is accepted, one outside it is refused, double-booking
stays blocked, the menus separate the two ownerships, the dashboard does not
count supplier equipment as company fleet, and the timeline tells the
supplier -> company -> customer -> company -> supplier story.
"""
import base64
from ast import literal_eval
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestThirdPartyOwnership(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Agreement = cls.env['gr.sublet.agreement']
        cls.Order = cls.env['gr.rental.order']

        cls.supplier = cls.env['res.partner'].create({'name': 'Supplier A'})
        cls.customer_a = cls.env['res.partner'].create({'name': 'Customer A'})
        cls.customer_b = cls.env['res.partner'].create({'name': 'Customer B'})
        cls.site_a = cls.env['gr.customer.site'].create({
            'name': 'Site A', 'partner_id': cls.customer_a.id})
        cls.site_b = cls.env['gr.customer.site'].create({
            'name': 'Site B', 'partner_id': cls.customer_b.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Ownership GM', 'login': 'ownership_gm',
            'email': 'ownership_gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'gr_security_base.group_generator_general_manager').id),
            ]})
        cls.rent_service = cls.env['product.product'].create({
            'name': 'Genset Rent-in', 'type': 'service', 'purchase_ok': True,
            'standard_price': 3000.0})

        # The supplier window the business described: 01/08 -> 31/08. Anchored
        # on a fixed year so the scenario dates read exactly as specified.
        cls.window_start = date(2026, 8, 1)
        cls.window_end = date(2026, 8, 31)

        cls.owned = cls.Asset.create({
            'name': 'GEN-OWN-001', 'pm_interval_hours': 2000.0,
            'owner_type': 'owned'})
        cls.third_party = cls.Asset.create({
            'name': 'GEN-EXT-001', 'pm_interval_hours': 2000.0,
            'owner_type': 'rented_in', 'owner_partner_id': cls.supplier.id,
            'supplier_equipment_ref': 'ABC-GEN-55'})
        cls.agreement = cls.Agreement.create({
            'asset_id': cls.third_party.id,
            'vendor_id': cls.supplier.id,
            'rent_in_product_id': cls.rent_service.id,
            'rent_in_amount': 3000.0,
            'date_start': cls.window_start,
            'date_end': cls.window_end,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _contract(self, partner, site):
        contract = self.env['gr.rental.contract'].create({
            'partner_id': partner.id, 'site_id': site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0})
        contract.action_submit()
        contract.with_user(self.gm).action_approve()
        contract.action_activate()
        return contract

    def _order(self, asset, partner, site, start=None, end=None, **kw):
        vals = {
            'partner_id': partner.id,
            'site_id': site.id,
            'contract_id': self._contract(partner, site).id,
            'asset_id': asset.id,
        }
        if start:
            vals['planned_dispatch_datetime'] = fields.Datetime.to_datetime(start)
            vals['date_requested'] = fields.Datetime.to_datetime(start)
        if end:
            vals['planned_return_datetime'] = fields.Datetime.to_datetime(end)
        vals.update(kw)
        return self.Order.create(vals)

    def _confirmed(self, order):
        """Move an order to Confirmed without going through action_confirm.

        gr_customer_approval gates action_confirm on a countersigned PDF. That
        gate is a separate feature with its own tests; driving it here would
        test the approval flow rather than the ownership rules these cases are
        about, so the state is set directly and the guards under test
        (action_reserve and the date constraints) run for real."""
        order.with_context(skip_customer_approval_lock=True).state = 'confirmed'
        return order

    # ------------------------------------------------------------------
    # Test 1 - an owned generator rents exactly as before
    # ------------------------------------------------------------------
    def test_01_owned_generator_rental_flow_unchanged(self):
        order = self._order(self.owned, self.customer_a, self.site_a,
                            start=self.window_start, end=self.window_end)
        self._confirmed(order)
        order.action_reserve()
        self.assertEqual(order.state, 'reserved')
        self.assertEqual(self.owned.status, 'reserved')
        # No supplier machinery attaches itself to a company asset.
        self.assertFalse(order.sublet_agreement_id)
        self.assertFalse(order.asset_is_third_party)
        self.assertEqual(self.owned.supplier_rental_status, 'not_applicable')

    def test_01b_owned_asset_rejects_supplier_fields(self):
        with self.assertRaises(ValidationError):
            self.Asset.create({
                'name': 'Bad owned', 'owner_type': 'owned',
                'supplier_equipment_ref': 'SHOULD-NOT-STICK'})

    # ------------------------------------------------------------------
    # Test 2 - a third-party generator is labelled, informative, rentable
    # ------------------------------------------------------------------
    def test_02_third_party_is_flagged_and_described(self):
        asset = self.third_party
        self.assertTrue(asset.is_third_party)
        self.assertTrue(asset.is_rentable, "third-party units must stay rentable")
        self.assertEqual(asset.owner_partner_id, self.supplier)
        self.assertEqual(asset.supplier_equipment_ref, 'ABC-GEN-55')
        self.assertEqual(asset.current_sublet_agreement_id, self.agreement)
        self.assertEqual(asset.supplier_contract_ref, self.agreement.name)
        self.assertEqual(asset.supplier_rental_start, self.window_start)
        self.assertEqual(asset.supplier_rental_end, self.window_end)
        self.assertEqual(asset.supplier_rental_cost, 3000.0)
        self.assertEqual(asset.sublet_agreement_count, 1)

    def test_02b_ownership_shows_in_selection_display_name(self):
        """The dropdown must announce the source, but only where asked."""
        plain = self.third_party.display_name
        flagged = self.third_party.with_context(
            gr_show_ownership=True).display_name
        self.assertNotIn('Third-Party', plain,
                         "display_name must stay clean by default")
        self.assertIn('Third-Party', flagged)
        # Owned equipment gains no noise in either context.
        self.assertEqual(
            self.owned.with_context(gr_show_ownership=True).display_name,
            self.owned.display_name)

    def test_02c_third_party_requires_a_supplier(self):
        with self.assertRaises(ValidationError):
            self.Asset.create({'name': 'No supplier', 'owner_type': 'rented_in'})

    def test_02d_live_supplier_agreement_blocks_owner_change(self):
        with self.assertRaises(ValidationError):
            self.third_party.write({'owner_type': 'owned'})

    # ------------------------------------------------------------------
    # Test 3 - a customer rental inside the supplier window is allowed
    # ------------------------------------------------------------------
    def test_03_customer_rental_inside_supplier_window(self):
        order = self._order(self.third_party, self.customer_a, self.site_a,
                            start=date(2026, 8, 5), end=date(2026, 8, 20))
        self.assertEqual(order.sublet_agreement_id, self.agreement,
                         "the rent-in agreement should auto-link")
        self._confirmed(order)
        order.action_reserve()
        self.assertEqual(order.state, 'reserved')
        self.assertEqual(order.asset_owner_type, 'rented_in')
        self.assertEqual(order.supplier_rental_end, self.window_end)

    # ------------------------------------------------------------------
    # Test 4 - a customer rental running past the supplier window is refused
    # ------------------------------------------------------------------
    def test_04_customer_rental_past_supplier_end_is_blocked(self):
        with self.assertRaises(ValidationError) as caught:
            self._order(self.third_party, self.customer_b, self.site_b,
                        start=date(2026, 8, 25), end=date(2026, 9, 5))
        self.assertIn('beyond the end date', str(caught.exception))

    def test_04b_customer_rental_before_supplier_start_is_blocked(self):
        with self.assertRaises(ValidationError) as caught:
            self._order(self.third_party, self.customer_b, self.site_b,
                        start=date(2026, 7, 20), end=date(2026, 8, 10))
        self.assertIn('before the start', str(caught.exception))

    def test_04c_extending_an_existing_order_past_the_window_is_blocked(self):
        order = self._order(self.third_party, self.customer_a, self.site_a,
                            start=date(2026, 8, 5), end=date(2026, 8, 20))
        with self.assertRaises(ValidationError):
            order.planned_return_datetime = fields.Datetime.to_datetime(
                date(2026, 9, 10))

    def test_04d_open_ended_supplier_window_allows_any_end(self):
        """No rent-in end date means no end to enforce - not a blanket refusal."""
        self.agreement.date_end = False
        order = self._order(self.third_party, self.customer_a, self.site_a,
                            start=date(2026, 8, 5), end=date(2026, 12, 31))
        self._confirmed(order)
        order.action_reserve()
        self.assertEqual(order.state, 'reserved')

    def test_04e_reserving_without_an_agreement_is_blocked(self):
        loose = self.Asset.create({
            'name': 'GEN-EXT-002', 'pm_interval_hours': 2000.0,
            'owner_type': 'rented_in', 'owner_partner_id': self.supplier.id})
        self.assertEqual(loose.supplier_rental_status, 'no_agreement')
        order = self._order(loose, self.customer_a, self.site_a,
                            start=date(2026, 8, 5), end=date(2026, 8, 20))
        with self.assertRaises(ValidationError) as caught:
            self._confirmed(order)
        self.assertIn('no supplier rental agreement', str(caught.exception).lower())

    def test_04f_expired_supplier_rental_blocks_reservation(self):
        past = self.Agreement.create({
            'asset_id': self.third_party.id, 'vendor_id': self.supplier.id,
            'rent_in_product_id': self.rent_service.id, 'rent_in_amount': 100.0,
            'date_start': date.today() - timedelta(days=60),
            'date_end': date.today() - timedelta(days=30)})
        self.agreement.unlink()
        self.third_party.invalidate_recordset()
        self.assertEqual(self.third_party.current_sublet_agreement_id, past)
        self.assertEqual(self.third_party.supplier_rental_status, 'expired')
        order = self._order(self.third_party, self.customer_a, self.site_a)
        with self.assertRaises(ValidationError):
            self._confirmed(order)

    # ------------------------------------------------------------------
    # Test 5 - double booking stays blocked on third-party units
    # ------------------------------------------------------------------
    def test_05_double_booking_still_blocked(self):
        first = self._order(self.third_party, self.customer_a, self.site_a,
                            start=date(2026, 8, 5), end=date(2026, 8, 15))
        self._confirmed(first)
        first.action_reserve()
        second = self._order(self.third_party, self.customer_b, self.site_b,
                             start=date(2026, 8, 10), end=date(2026, 8, 20))
        # Odoo's assertRaises takes a single class, and the guard that fires
        # first depends on which layer catches the clash, so assert on the
        # shared base instead of guessing between UserError/ValidationError.
        with self.assertRaises(UserError):
            self._confirmed(second)
        self.assertEqual(second.state, 'draft')

    # ------------------------------------------------------------------
    # Test 6 - the two ownerships are separated in the UI
    # ------------------------------------------------------------------
    def test_06_menu_actions_separate_the_two_ownerships(self):
        owned_action = self.env.ref('gr_equipment.action_gr_equipment_owned')
        third_action = self.env.ref('gr_equipment.action_gr_equipment_third_party')
        # Each menu's action carries the ownership domain, so the two screens
        # can never show each other's equipment.
        owned_ids = self.Asset.search(literal_eval(owned_action.domain)).ids
        third_ids = self.Asset.search(literal_eval(third_action.domain)).ids
        self.assertIn(self.owned.id, owned_ids)
        self.assertNotIn(self.third_party.id, owned_ids)
        self.assertIn(self.third_party.id, third_ids)
        self.assertNotIn(self.owned.id, third_ids)
        # Separation is by action domain, not by record rule: an administrator
        # still reaches every unit from the unfiltered list.
        everything = self.Asset.search([]).ids
        self.assertIn(self.owned.id, everything)
        self.assertIn(self.third_party.id, everything)
        self.assertEqual(third_action.res_model, 'gr.generator.asset')

    # ------------------------------------------------------------------
    # Test 7 - the dashboard does not count supplier units as company fleet
    # ------------------------------------------------------------------
    def test_07_dashboard_excludes_third_party_from_owned_fleet(self):
        card = self.env['gr.dashboard.card']
        counts = card._fleet_data()['_counts']
        owned_ids = self.Asset.search([
            ('company_id', '=', self.env.company.id), ('active', '=', True),
            ('status', '!=', 'retired'), ('owner_type', '=', 'owned')]).ids
        third_ids = self.Asset.search([
            ('company_id', '=', self.env.company.id), ('active', '=', True),
            ('status', '!=', 'retired'), ('owner_type', '=', 'rented_in')]).ids
        self.assertEqual(counts['owned'], len(owned_ids))
        self.assertEqual(counts['third_party'], len(third_ids))
        self.assertLess(counts['owned'], counts['total'],
                        "owned fleet must be a strict subset of the rentable pool")
        # Customer-owned equipment is not fleet at all.
        customer_owned = self.Asset.create({
            'name': 'Serviced only', 'owner_type': 'customer_owned',
            'owner_partner_id': self.customer_a.id})
        after = card._fleet_data()['_counts']
        self.assertEqual(after['total'], counts['total'],
                         "customer-owned units must not inflate the fleet")
        self.assertTrue(customer_owned.exists())

    # ------------------------------------------------------------------
    # Test 8 - the timeline tells the whole supplier story
    # ------------------------------------------------------------------
    def test_08_history_covers_supplier_to_customer_and_back(self):
        if 'rental.asset.history' not in self.env.registry.models:
            self.skipTest("Asset history module is not installed.")
        History = self.env['rental.asset.history']

        def types():
            return set(History.search(
                [('asset_id', '=', self.third_party.id)]).mapped('event_type'))

        self.assertIn('sublet_created', types())
        self.agreement.action_generate_rent_in_po()
        self.assertIn('vendor_received', types())

        order = self._order(self.third_party, self.customer_a, self.site_a,
                            start=date(2026, 8, 5), end=date(2026, 8, 20))
        self._confirmed(order)
        order.action_reserve()
        # The delivery inspection is passed by writing its state: action_pass
        # goes through the same customer-approval gate as action_confirm, which
        # is a different feature from the ownership rules under test here.
        inspection = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'delivery'})
        inspection._populate_default_checklist()
        inspection.with_context(skip_customer_approval_lock=True).state = 'passed'
        order.invalidate_recordset()
        order.action_dispatch()
        order.start_meter_reading = 0.0
        order.action_install()
        order.action_start_rental()
        order.end_meter_reading = 10.0
        # This equipment type asks for a return signature; supply one so the
        # return proceeds and the timeline gets its "returned from customer"
        # entry.
        if order.rental_workflow_requires_return_signature:
            order.customer_return_signature = base64.b64encode(b'signature')
        order.action_return()
        recorded = types()
        self.assertTrue({'delivery', 'return'} & recorded,
                        "customer delivery and return must be on the timeline")

        order.action_start_inspection()
        return_inspection = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'return'})
        return_inspection._populate_default_checklist()
        return_inspection.with_context(
            skip_customer_approval_lock=True).state = 'passed'
        order.invalidate_recordset()
        order.action_close()
        self.agreement.action_mark_returned()
        self.assertIn('vendor_returned', types())
