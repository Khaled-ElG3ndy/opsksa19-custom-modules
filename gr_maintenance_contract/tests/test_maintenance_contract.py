# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestMaintenanceContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MC = cls.env['gr.maintenance.contract']
        cls.Asset = cls.env['gr.generator.asset']
        cls.customer = cls.env['res.partner'].create({'name': 'Perkins Owner'})
        # customer-owned unit (M11)
        cls.cust_asset = cls.Asset.create({
            'name': 'Perkins 160kVA', 'pm_interval_hours': 500.0,
            'owner_type': 'customer_owned', 'owner_partner_id': cls.customer.id})
        cls.owned_asset = cls.Asset.create({
            'name': 'Owned Gen MC', 'pm_interval_hours': 2000.0})

    def _contract(self, **kw):
        vals = {
            'partner_id': self.customer.id, 'asset_id': self.cust_asset.id,
            'date_start': date(2026, 1, 1),
            'visit_interval_months': 1, 'visits_total': 12,
            'oil_filter_interval_months': 6, 'battery_once': True,
            'annual_price': 9500.0, 'payment_split_count': 2,
            'emergency_visit_rate': 1500.0, 'emergency_response_hours': 24,
        }
        vals.update(kw)
        return self.MC.create(vals)

    # ---------- sequence + constraint ----------
    def test_sequence_generation(self):
        c = self._contract()
        self.assertTrue(c.name.startswith('GR/MC/'))

    def test_requires_customer_owned(self):
        with self.assertRaises(UserError):
            self._contract(asset_id=self.owned_asset.id)

    def test_partner_defaults_from_owner(self):
        c = self.MC.new({'asset_id': self.cust_asset.id})
        c._onchange_asset()
        self.assertEqual(c.partner_id, self.customer)

    # ---------- activation generates visits ----------
    def test_activate_generates_visits(self):
        c = self._contract()
        c.action_activate()
        self.assertEqual(c.state, 'active')
        covered = c.visit_ids.filtered(lambda j: j.contract_coverage == 'covered')
        self.assertEqual(len(covered), 12)
        # all covered visits are preventive M7 jobs on the customer unit
        self.assertTrue(all(j.job_type == 'preventive' for j in covered))
        self.assertTrue(all(j.asset_id == self.cust_asset for j in covered))

    def test_activate_derives_end_date(self):
        c = self._contract(date_end=False)
        c.action_activate()
        self.assertTrue(c.date_end)

    def test_total_visits_suggested_from_range_and_interval(self):
        c = self._contract(
            date_start=date(2026, 7, 8),
            date_end=date(2027, 7, 8),
            visit_interval_months=3,
        )
        self.assertEqual(c.visits_total, 12)  # explicit value is respected

        c = self.MC.create({
            'partner_id': self.customer.id,
            'asset_id': self.cust_asset.id,
            'date_start': date(2026, 7, 8),
            'date_end': date(2027, 7, 8),
            'visit_interval_months': 3,
        })
        self.assertEqual(c.visits_total, 4)

    def test_total_visits_recalculates_on_schedule_change(self):
        c = self._contract()
        c.write({
            'date_start': date(2026, 7, 8),
            'date_end': date(2027, 7, 8),
            'visit_interval_months': 3,
        })
        self.assertEqual(c.visits_total, 4)

    def test_total_visits_manual_override_is_kept(self):
        c = self._contract()
        c.write({
            'date_start': date(2026, 7, 8),
            'date_end': date(2027, 7, 8),
            'visit_interval_months': 3,
            'visits_total': 6,
        })
        self.assertEqual(c.visits_total, 6)

    def test_oil_filter_cadence(self):
        c = self._contract()
        c.action_activate()
        covered = c.visit_ids.filtered(lambda j: j.contract_coverage == 'covered')
        oil_due = covered.filtered(lambda j: j.oil_filter_due)
        # months 0 and 6 within a 12-visit monthly plan -> 2 oil-due visits
        self.assertEqual(len(oil_due), 2)

    # ---------- payment schedule ----------
    def test_payment_schedule_split(self):
        c = self._contract()
        c.action_activate()
        self.assertEqual(len(c.schedule_line_ids), 2)
        total = sum(c.schedule_line_ids.mapped('amount'))
        self.assertAlmostEqual(total, 9500.0, places=2)
        self.assertAlmostEqual(c.schedule_line_ids[0].amount, 4750.0, places=2)

    def test_payment_creates_invoice(self):
        c = self._contract()
        c.action_activate()
        pay = c.schedule_line_ids[0]
        pay.action_create_invoice()
        self.assertEqual(pay.state, 'invoiced')
        self.assertTrue(pay.invoice_id)
        self.assertEqual(pay.invoice_id.move_type, 'out_invoice')
        self.assertEqual(pay.invoice_id.invoice_origin, c.name)

    def test_payment_no_double_invoice(self):
        c = self._contract()
        c.action_activate()
        pay = c.schedule_line_ids[0]
        pay.action_create_invoice()
        with self.assertRaises(UserError):
            pay.action_create_invoice()

    # ---------- emergency / T&M ----------
    def test_log_emergency_visit(self):
        c = self._contract()
        c.action_activate()
        act = c.action_log_emergency_visit()
        job = self.env['gr.maintenance.job'].browse(act['res_id'])
        self.assertEqual(job.contract_coverage, 'tm')
        self.assertEqual(job.job_type, 'corrective')
        self.assertAlmostEqual(job.tm_charge, 1500.0)

    def test_covered_vs_tm_counts(self):
        c = self._contract()
        c.action_activate()
        c.action_log_emergency_visit()
        c.invalidate_recordset()
        self.assertEqual(c.covered_visit_count, 12)
        self.assertEqual(c.tm_visit_count, 1)

    # ---------- lifecycle ----------
    def test_only_draft_activates(self):
        c = self._contract()
        c.action_activate()
        with self.assertRaises(UserError):
            c.action_activate()

    def test_cancel(self):
        c = self._contract()
        c.action_cancel()
        self.assertEqual(c.state, 'cancelled')
