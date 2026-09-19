# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestGeneratorAsset(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.company = cls.env.company

    def _make_asset(self, **kw):
        vals = {
            'name': 'Test Gen',
            'kva_rating': 500.0,
            'pm_interval_hours': 250.0,
        }
        vals.update(kw)
        return self.Asset.create(vals)

    # ----- creation & sequence -----
    def test_create_assigns_sequence_code(self):
        asset = self._make_asset()
        self.assertTrue(asset.code.startswith('GR/ASSET/'),
                        "Asset code should come from the GR/ASSET sequence")

    # ----- duplicate serial -----
    def test_duplicate_serial_blocked(self):
        self._make_asset(serial_number='SN-001')
        with self.assertRaises(ValidationError):
            self._make_asset(serial_number='SN-001')

    def test_same_serial_different_company_allowed(self):
        # Create a second company and confirm serial uniqueness is per-company.
        company2 = self.env['res.company'].create({'name': 'GenCo 2'})
        self._make_asset(serial_number='SN-SHARED')
        a2 = self.Asset.create({
            'name': 'Other Co Gen',
            'serial_number': 'SN-SHARED',
            'company_id': company2.id,
        })
        self.assertTrue(a2.id)

    # ----- negative meter -----
    def test_negative_meter_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_asset(current_hour_meter=-5.0)

    # ----- meter rollback -----
    def test_meter_rollback_blocked(self):
        asset = self._make_asset(current_hour_meter=100.0)
        # A plain edit may never reduce the meter below its current value.
        with self.assertRaises(UserError):
            asset.write({'current_hour_meter': 90.0})

    def test_meter_increase_allowed(self):
        asset = self._make_asset(current_hour_meter=100.0)
        asset.write({'current_hour_meter': 150.0})
        self.assertEqual(asset.current_hour_meter, 150.0)

    # ----- available vs maintenance overdue -----
    def test_available_blocked_when_overdue(self):
        # interval 100, last_pm 0 => next_pm 100; meter 120 => overdue
        asset = self._make_asset(
            pm_interval_hours=100.0, last_pm_hour=0.0, current_hour_meter=120.0,
            status='under_maintenance')
        self.assertTrue(asset.maintenance_overdue)
        with self.assertRaises(ValidationError):
            asset.write({'status': 'available'})

    def test_action_set_available_blocked_when_breakdown(self):
        asset = self._make_asset(status='breakdown')
        with self.assertRaises(UserError):
            asset.action_set_available()

    # ----- retire guard -----
    def test_retire_blocked_with_active_rental(self):
        asset = self._make_asset(current_rental_order_ref='GR/RO/00001')
        with self.assertRaises(UserError):
            asset.action_retire()

    def test_retire_ok_when_idle(self):
        asset = self._make_asset()
        asset.action_retire()
        self.assertEqual(asset.status, 'retired')
        self.assertFalse(asset.active)

    # ----- computed fields -----
    def test_next_pm_and_profitability_compute(self):
        asset = self._make_asset(last_pm_hour=200.0, pm_interval_hours=250.0,
                                 revenue_total=10000.0, cost_total=3500.0)
        self.assertEqual(asset.next_pm_hour, 450.0)
        self.assertEqual(asset.profitability, 6500.0)


@tagged('post_install', '-at_install')
class TestMeterCorrectionWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Wizard = cls.env['gr.generator.asset.meter.correction.wizard']

    def _admin_user(self):
        user = self.env['res.users'].create({
            'name': 'Gen Admin', 'login': 'gen_admin_test',
            'email': 'gen_admin_test@example.com',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('gr_security_base.group_generator_administrator').id),
            ],
        })
        return user

    def _maint_manager_user(self):
        user = self.env['res.users'].create({
            'name': 'Maint Mgr', 'login': 'maint_mgr_test',
            'email': 'maint_mgr_test@example.com',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('gr_security_base.group_generator_maint_manager').id),
            ],
        })
        return user

    def test_increase_correction_by_manager(self):
        asset = self.Asset.create({'name': 'WizGen', 'current_hour_meter': 100.0})
        mgr = self._maint_manager_user()
        wiz = self.Wizard.with_user(mgr).create({
            'asset_id': asset.id, 'new_meter': 130.0, 'reason': 'On-site recount'})
        wiz.action_apply()
        self.assertEqual(asset.current_hour_meter, 130.0)
        self.assertEqual(asset.last_verified_hour_meter, 130.0)

    def test_decrease_blocked_for_manager(self):
        asset = self.Asset.create({'name': 'WizGen2', 'current_hour_meter': 100.0})
        mgr = self._maint_manager_user()
        wiz = self.Wizard.with_user(mgr).create({
            'asset_id': asset.id, 'new_meter': 80.0, 'reason': 'Meter swap'})
        with self.assertRaises(UserError):
            wiz.action_apply()

    def test_decrease_allowed_for_admin(self):
        asset = self.Asset.create({'name': 'WizGen3', 'current_hour_meter': 100.0})
        admin = self._admin_user()
        wiz = self.Wizard.with_user(admin).create({
            'asset_id': asset.id, 'new_meter': 80.0, 'reason': 'New meter unit fitted'})
        wiz.action_apply()
        self.assertEqual(asset.current_hour_meter, 80.0)
