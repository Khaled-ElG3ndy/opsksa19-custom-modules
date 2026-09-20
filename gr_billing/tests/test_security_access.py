# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGeneratorSecurityAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Generator Security Customer',
        })
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Generator Security Site',
            'partner_id': cls.partner.id,
        })
        cls.asset = cls.env['gr.generator.asset'].create({
            'name': 'Security Generator',
            'code': 'SEC-GEN-001',
            'serial_number': 'SEC-GEN-SN-001',
            'pm_interval_hours': 1000.0,
        })
        cls.order = cls.env['gr.rental.order'].create({
            'partner_id': cls.partner.id,
            'site_id': cls.site.id,
            'asset_id': cls.asset.id,
        })
        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner.id,
            'rental_order_id': cls.order.id,
        })
        cls.internal_user = cls._make_user(
            'generator-security-internal',
            ['base.group_user'])
        cls.stock_user = cls._make_user(
            'generator-security-stock',
            ['base.group_user', 'stock.group_stock_user'])
        cls.sales_user = cls._make_user(
            'generator-security-sales',
            ['base.group_user', 'sales_team.group_sale_salesman'])
        cls.generator_user = cls._make_user(
            'generator-security-granted',
            ['gr_security_base.group_generator_user'])
        cls.generator_admin = cls._make_user(
            'generator-security-admin',
            ['gr_security_base.group_generator_administrator'])
        cls.generator_account_user = cls._make_user(
            'generator-security-account-granted',
            ['gr_security_base.group_generator_user', 'account.group_account_readonly'])
        cls.generator_account_admin = cls._make_user(
            'generator-security-account-admin',
            [
                'gr_security_base.group_generator_administrator',
                'account.group_account_readonly',
            ])

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
            self.env['gr.rental.order'].with_user(user).search([], limit=1)

    def test_plain_users_cannot_reach_generator_custom_models(self):
        for user in (self.internal_user, self.stock_user, self.sales_user):
            self._assert_custom_model_denied(user)

    def test_plain_account_user_cannot_see_generator_invoice(self):
        account_user = self._make_user(
            'generator-security-account',
            ['base.group_user', 'account.group_account_readonly'])
        moves = self.env['account.move'].with_user(account_user).search([
            ('id', '=', self.invoice.id),
        ])
        self.assertFalse(moves)

    def test_generator_users_can_read_custom_and_shared_records(self):
        for user in (self.generator_user, self.generator_admin):
            self.assertIn(
                self.order,
                self.env['gr.rental.order'].with_user(user).search([
                    ('id', '=', self.order.id),
                ]))

        for user in (self.generator_account_user, self.generator_account_admin):
            self.assertIn(
                self.invoice,
                self.env['account.move'].with_user(user).search([
                    ('id', '=', self.invoice.id),
                ]))
