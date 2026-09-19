# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCabinDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The dashboard is gated on a Cabin Rental role (strx_cabin_security);
        # holding Inventory User is deliberately no longer enough.
        cls.env.user.group_ids = [
            (4, cls.env.ref('strx_cabin_security.group_cabin_user').id)]
        cls.partner = cls.env['res.partner'].create({
            'name': 'Dashboard Customer',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Dashboard Cabin 5x3',
            'default_code': 'DASH-CAB-5X3',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'strx_is_cabin': True,
            'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3',
            'strx_cabin_grade': 'std',
        })
        cls.available_lot = cls.env['stock.lot'].create({
            'name': 'DASH-AVAILABLE',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
        })
        cls.rented_lot = cls.env['stock.lot'].create({
            'name': 'DASH-RENTED',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
        })
        cls.rented_lot._strx_set_readiness(
            'on_rent', reason='Dashboard fixture')
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 1,
            })],
        })
        cls.allocation = cls.env['strx.cabin.allocation'].create({
            'order_line_id': cls.order.order_line[0].id,
            'lot_id': cls.available_lot.id,
        })

    def test_dashboard_payload_contains_operational_data(self):
        data = self.env['strx.cabin.dashboard'].get_dashboard_data()

        self.assertGreaterEqual(data['kpis']['total_cabins'], 2)
        self.assertGreaterEqual(data['kpis']['available'], 1)
        self.assertGreaterEqual(data['kpis']['on_rent'], 1)
        self.assertEqual(
            sum(item['count'] for item in data['distribution']),
            data['kpis']['total_cabins'])
        self.assertIn(
            self.allocation.name,
            [item['name'] for item in data['recent_allocations']])
        self.assertIn('overdue_returns', data['alerts'])
        self.assertIn('create_allocation', data['permissions'])

    def test_dashboard_payload_follows_user_language(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module'].search([
            ('name', '=', 'strx_cabin_dashboard'),
            ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])

        english = self.env['strx.cabin.dashboard'].with_context(
            lang='en_US').get_dashboard_data()
        arabic = self.env['strx.cabin.dashboard'].with_context(
            lang='ar_001').get_dashboard_data()

        self.assertEqual(english['distribution'][0]['label'], 'Available')
        self.assertEqual(arabic['distribution'][0]['label'], 'متاحة')

    def test_dashboard_rejects_user_without_inventory_access(self):
        user = self.env['res.users'].create({
            'name': 'Dashboard Unauthorized User',
            'login': 'dashboard-no-stock',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['strx.cabin.dashboard'].with_user(
                user).get_dashboard_data()

