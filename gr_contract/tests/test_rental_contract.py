# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestRentalContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Contract = cls.env['gr.rental.contract']
        cls.Amendment = cls.env['gr.contract.amendment']
        cls.partner = cls.env['res.partner'].create({'name': 'Contract Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Contract Site', 'partner_id': cls.partner.id})

    def _gm_user(self):
        return self.env['res.users'].create({
            'name': 'Contract GM', 'login': 'contract_gm_test',
            'email': 'contract_gm@example.com',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('gr_security_base.group_generator_general_manager').id),
            ],
        })

    def _sales_user(self):
        return self.env['res.users'].create({
            'name': 'Contract Sales', 'login': 'contract_sales_test',
            'email': 'contract_sales@example.com',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('gr_security_base.group_generator_sales_officer').id),
            ],
        })

    def _make_contract(self, **kw):
        vals = {
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0,
            'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0,
        }
        vals.update(kw)
        return self.Contract.create(vals)

    # ----- creation & sequence -----
    def test_create_assigns_sequence(self):
        c = self._make_contract()
        self.assertTrue(c.name.startswith('GR/CON/'))

    # ----- hours constraint -----
    def test_max_hours_must_exceed_included(self):
        with self.assertRaises(ValidationError):
            self._make_contract(included_hours_per_day=12.0, max_hours_per_day=8.0)

    def test_equal_hours_allowed(self):
        c = self._make_contract(included_hours_per_day=10.0, max_hours_per_day=10.0)
        self.assertTrue(c.id)

    # ----- date constraint -----
    def test_end_before_start_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_contract(date_start='2026-06-10', date_end='2026-06-01')

    # ----- approval requires manager -----
    def test_sales_cannot_approve(self):
        c = self._make_contract()
        c.action_submit()
        sales = self._sales_user()
        with self.assertRaises(UserError):
            c.with_user(sales).action_approve()

    def test_gm_can_approve(self):
        c = self._make_contract()
        c.action_submit()
        gm = self._gm_user()
        c.with_user(gm).action_approve()
        self.assertEqual(c.state, 'approved')

    # ----- activation requires rates and site -----
    def test_activate_requires_rates(self):
        c = self._make_contract(base_daily_rate=0.0, base_monthly_rate=0.0,
                                hourly_rate=0.0, standby_rate=0.0, overtime_hour_rate=0.0)
        c.action_submit()
        gm = self._gm_user()
        # approval itself should fail for no rates
        with self.assertRaises(UserError):
            c.with_user(gm).action_approve()

    # ----- approval lock -----
    def test_commercial_fields_locked_after_approval(self):
        c = self._make_contract()
        c.action_submit()
        gm = self._gm_user()
        c.with_user(gm).action_approve()
        # Direct edit of a locked commercial field must be blocked.
        with self.assertRaises(UserError):
            c.write({'base_daily_rate': 2000.0})

    def test_noncommercial_field_editable_after_approval(self):
        c = self._make_contract()
        c.action_submit()
        gm = self._gm_user()
        c.with_user(gm).action_approve()
        # Notes is not a locked field; should be writable.
        c.write({'notes': 'Updated after approval'})
        self.assertEqual(c.notes, 'Updated after approval')

    # ----- monthly sales follow-up -----
    def test_monthly_sales_followup_cron_creates_activity_once(self):
        sales = self._sales_user()
        c = self._make_contract(
            sales_user_id=sales.id,
            sales_monthly_reminder_day=1,
            date_end=fields.Date.context_today(self.Contract) + timedelta(days=5),
        )
        c.action_submit()
        c.with_user(self._gm_user()).action_approve()
        c.action_activate()

        period = c._sales_followup_period(fields.Date.context_today(c))
        self.Contract._cron_monthly_sales_followups()
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'gr.rental.contract'),
            ('res_id', '=', c.id),
            ('summary', '=', c._sales_followup_summary(period)),
        ])
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, sales)
        self.assertIn(self.partner.name, activities.note)
        self.assertIn('Issue or coordinate the monthly customer invoice',
                      activities.note)
        self.assertEqual(c.last_sales_followup_period, period)

        self.Contract._cron_monthly_sales_followups()
        self.assertEqual(self.env['mail.activity'].search_count([
            ('res_model', '=', 'gr.rental.contract'),
            ('res_id', '=', c.id),
            ('summary', '=', c._sales_followup_summary(period)),
        ]), 1)

    def test_disabled_monthly_sales_followup_is_ignored(self):
        c = self._make_contract(
            sales_monthly_reminder_enabled=False,
            sales_monthly_reminder_day=1,
        )
        c.action_submit()
        c.with_user(self._gm_user()).action_approve()
        c.action_activate()

        self.Contract._cron_monthly_sales_followups()
        self.assertFalse(self.env['mail.activity'].search([
            ('res_model', '=', 'gr.rental.contract'),
            ('res_id', '=', c.id),
        ]))

    def test_manual_monthly_sales_followup_button(self):
        c = self._make_contract(sales_monthly_reminder_day=1)
        c.action_submit()
        c.with_user(self._gm_user()).action_approve()

        c.action_raise_monthly_sales_followup()
        self.assertTrue(self.env['mail.activity'].search([
            ('res_model', '=', 'gr.rental.contract'),
            ('res_id', '=', c.id),
        ]))

    def test_sales_reminder_day_must_exist_every_month(self):
        with self.assertRaises(ValidationError):
            self._make_contract(sales_monthly_reminder_day=31)

    # ----- amendment workflow -----
    def test_amendment_applies_change(self):
        c = self._make_contract()
        c.action_submit()
        gm = self._gm_user()
        c.with_user(gm).action_approve()
        original = c.base_daily_rate

        amend = self.Amendment.create({
            'contract_id': c.id,
            'reason': 'Price increase agreed',
            'new_base_daily_rate': 1500.0,
        })
        amend.action_submit()
        amend.with_user(gm).action_approve()
        amend.action_apply()

        self.assertEqual(amend.state, 'applied')
        self.assertEqual(c.base_daily_rate, 1500.0)
        self.assertNotEqual(c.base_daily_rate, original)
        self.assertTrue(amend.old_values_json)
        self.assertTrue(amend.new_values_json)

    def test_amendment_requires_manager_approval(self):
        c = self._make_contract()
        c.action_submit()
        gm = self._gm_user()
        c.with_user(gm).action_approve()
        amend = self.Amendment.create({
            'contract_id': c.id, 'reason': 'x', 'new_hourly_rate': 50.0})
        amend.action_submit()
        sales = self._sales_user()
        with self.assertRaises(UserError):
            amend.with_user(sales).action_approve()

    def test_amendment_apply_requires_approved(self):
        c = self._make_contract()
        amend = self.Amendment.create({
            'contract_id': c.id, 'reason': 'x', 'new_hourly_rate': 50.0})
        # Not approved yet -> apply must fail.
        with self.assertRaises(UserError):
            amend.action_apply()

    # ----- state machine guards -----
    def test_cannot_approve_from_draft(self):
        c = self._make_contract()
        gm = self._gm_user()
        with self.assertRaises(UserError):
            c.with_user(gm).action_approve()  # must be submitted first

    def test_full_lifecycle(self):
        c = self._make_contract()
        gm = self._gm_user()
        c.action_submit()
        c.with_user(gm).action_approve()
        c.action_activate()
        self.assertEqual(c.state, 'active')
        c.action_suspend()
        self.assertEqual(c.state, 'suspended')
        c.action_activate()
        self.assertEqual(c.state, 'active')
        c.action_close()
        self.assertEqual(c.state, 'closed')
