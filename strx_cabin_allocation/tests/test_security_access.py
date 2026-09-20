# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCabinSecurityAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cabin Security Customer',
        })
        cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        cls.customer_loc = cls.env.ref('stock.stock_location_customers')
        cls.product = cls.env['product.product'].create({
            'name': 'Security Cabin 5x3',
            'default_code': 'SEC-CAB-5X3',
            'type': 'consu',
            'is_storable': True,
            'tracking': 'serial',
            'sale_ok': True,
            'invoice_policy': 'order',
            'list_price': 1000.0,
            'strx_is_cabin': True,
            'strx_asset_kind': 'cabin',
            'strx_cabin_size': '5x3',
            'strx_cabin_grade': 'std',
            'taxes_id': [(5, 0, 0)],
        })
        cls.lot = cls.env['stock.lot'].create({
            'name': 'SEC-CAB-SN-001',
            'product_id': cls.product.id,
            'company_id': cls.env.company.id,
        })
        cls.env['stock.quant']._update_available_quantity(
            cls.product, cls.stock_loc, 1.0, lot_id=cls.lot)
        cls.quant = cls.env['stock.quant'].search([
            ('product_id', '=', cls.product.id),
            ('lot_id', '=', cls.lot.id),
            ('location_id', '=', cls.stock_loc.id),
        ], limit=1)
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'order_line': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 1.0,
                'price_unit': cls.product.list_price,
            })],
        })
        cls.order.action_confirm()
        cls.order_line = cls.order.order_line.filtered(
            lambda line: line.product_id == cls.product)
        cls.allocation = cls.env['strx.cabin.allocation'].create({
            'order_line_id': cls.order_line.id,
            'lot_ids': [(6, 0, cls.lot.ids)],
        })
        cls.allocation.action_allocate()
        cls.invoice = cls.order._create_invoices()
        cls.invoice_line = cls.invoice.invoice_line_ids.filtered(
            lambda line: line.product_id == cls.product)
        cls.picking = cls.env['stock.picking'].create({
            'partner_id': cls.partner.id,
            'picking_type_id': cls.warehouse.out_type_id.id,
            'location_id': cls.stock_loc.id,
            'location_dest_id': cls.customer_loc.id,
            'move_ids': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 1.0,
                'product_uom': cls.product.uom_id.id,
                'location_id': cls.stock_loc.id,
                'location_dest_id': cls.customer_loc.id,
            })],
        })
        cls.move = cls.picking.move_ids[0]

        cls.internal_user = cls._make_user(
            'cabin-security-internal',
            ['base.group_user'])
        cls.stock_user = cls._make_user(
            'cabin-security-stock',
            ['base.group_user', 'stock.group_stock_user'])
        cls.sales_user = cls._make_user(
            'cabin-security-sales',
            ['base.group_user', 'sales_team.group_sale_manager'])
        cls.account_user = cls._make_user(
            'cabin-security-account',
            ['base.group_user', 'account.group_account_readonly'])
        cls.cabin_user = cls._make_user(
            'cabin-security-cabin',
            ['strx_cabin_security.group_cabin_user'])
        cls.cabin_sales_user = cls._make_user(
            'cabin-security-cabin-sales',
            ['strx_cabin_security.group_cabin_sales_officer'])
        cls.cabin_ops_user = cls._make_user(
            'cabin-security-cabin-ops',
            ['strx_cabin_security.group_cabin_operations_officer'])
        cls.cabin_account_user = cls._make_user(
            'cabin-security-cabin-account',
            [
                'strx_cabin_security.group_cabin_user',
                'account.group_account_readonly',
            ])
        cls.cabin_admin = cls._make_user(
            'cabin-security-cabin-admin',
            ['strx_cabin_security.group_cabin_administrator'])
        cls.order.write({'user_id': cls.cabin_sales_user.id})

    @classmethod
    def _make_user(cls, login, group_xmlids):
        return cls.env['res.users'].create({
            'name': login,
            'login': login,
            'email': '%s@example.com' % login,
            'group_ids': [(6, 0, [cls.env.ref(xmlid).id for xmlid in group_xmlids])],
        })

    def _assert_custom_model_denied(self, user):
        with self.assertRaises(AccessError):
            self.env['strx.cabin.allocation'].with_user(user).search([], limit=1)

    def test_plain_users_cannot_reach_cabin_custom_models(self):
        for user in (self.internal_user, self.stock_user, self.sales_user):
            self._assert_custom_model_denied(user)

    def test_plain_users_cannot_see_cabin_records_through_shared_models(self):
        for user in (self.internal_user, self.stock_user, self.sales_user):
            self.assertFalse(self.env['product.product'].with_user(user).search([
                ('id', '=', self.product.id),
            ]))
            self.assertFalse(self.env['product.template'].with_user(user).search([
                ('id', '=', self.product.product_tmpl_id.id),
            ]))

        self.assertFalse(self.env['stock.lot'].with_user(self.stock_user).search([
            ('id', '=', self.lot.id),
        ]))
        self.assertFalse(self.env['stock.quant'].with_user(self.stock_user).search([
            ('id', '=', self.quant.id),
        ]))
        self.assertFalse(self.env['stock.move'].with_user(self.stock_user).search([
            ('id', '=', self.move.id),
        ]))
        self.assertFalse(self.env['stock.picking'].with_user(self.stock_user).search([
            ('id', '=', self.picking.id),
        ]))
        self.assertFalse(self.env['sale.order'].with_user(self.sales_user).search([
            ('id', '=', self.order.id),
        ]))
        self.assertFalse(self.env['sale.order.line'].with_user(self.sales_user).search([
            ('id', '=', self.order_line.id),
        ]))
        self.assertFalse(self.env['account.move'].with_user(self.account_user).search([
            ('id', '=', self.invoice.id),
        ]))
        self.assertFalse(
            self.env['account.move.line'].with_user(self.account_user).search([
                ('id', '=', self.invoice_line.id),
            ]))

    def test_cabin_users_can_read_custom_and_shared_records(self):
        for user in (self.cabin_user, self.cabin_admin):
            self.assertIn(
                self.allocation,
                self.env['strx.cabin.allocation'].with_user(user).search([
                    ('id', '=', self.allocation.id),
                ]))
            self.assertIn(
                self.product,
                self.env['product.product'].with_user(user).search([
                    ('id', '=', self.product.id),
                ]))

        for user in (self.cabin_ops_user, self.cabin_admin):
            self.assertIn(
                self.lot,
                self.env['stock.lot'].with_user(user).search([
                    ('id', '=', self.lot.id),
                ]))
            self.assertIn(
                self.picking,
                self.env['stock.picking'].with_user(user).search([
                    ('id', '=', self.picking.id),
                ]))

        for user in (self.cabin_sales_user, self.cabin_admin):
            self.assertIn(
                self.order,
                self.env['sale.order'].with_user(user).search([
                    ('id', '=', self.order.id),
                ]))

        self.assertIn(
            self.invoice,
            self.env['account.move'].with_user(self.cabin_account_user).search([
                ('id', '=', self.invoice.id),
            ]))
