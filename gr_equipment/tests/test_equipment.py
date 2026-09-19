# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestEquipmentSpine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Order = cls.env['gr.rental.order']
        cls.vendor = cls.env['res.partner'].create({'name': 'Genset Vendor Co'})
        cls.customer = cls.env['res.partner'].create({'name': 'Owns-a-Perkins Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Eq Site', 'partner_id': cls.customer.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Eq GM', 'login': 'eq_gm', 'email': 'eqgm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})

    def _asset(self, **kw):
        vals = {'name': 'Eq Gen', 'pm_interval_hours': 2000.0}
        vals.update(kw)
        return self.Asset.create(vals)

    # ---------- defaults / backward compatibility ----------
    def test_default_owner_is_owned(self):
        a = self._asset()
        self.assertEqual(a.owner_type, 'owned')
        self.assertTrue(a.is_rentable)

    def test_owned_rejects_owner_partner(self):
        with self.assertRaises(ValidationError):
            self._asset(owner_type='owned', owner_partner_id=self.vendor.id)

    # ---------- rented-in ----------
    def test_rented_in_requires_vendor(self):
        with self.assertRaises(ValidationError):
            self._asset(owner_type='rented_in')  # no owner party

    def test_rented_in_is_rentable(self):
        a = self._asset(owner_type='rented_in', owner_partner_id=self.vendor.id)
        self.assertTrue(a.is_rentable)

    # ---------- customer-owned ----------
    def test_customer_owned_requires_party(self):
        with self.assertRaises(ValidationError):
            self._asset(owner_type='customer_owned')

    def test_customer_owned_not_rentable(self):
        a = self._asset(owner_type='customer_owned',
                        owner_partner_id=self.customer.id)
        self.assertFalse(a.is_rentable)

    def test_customer_owned_blocked_from_rental_status(self):
        a = self._asset(owner_type='customer_owned',
                        owner_partner_id=self.customer.id)
        # trying to force it into a rental status must fail
        with self.assertRaises(ValidationError):
            a.status = 'on_rent'

    def test_customer_owned_blocked_on_rental_order(self):
        a = self._asset(owner_type='customer_owned',
                        owner_partner_id=self.customer.id)
        c = self._contract(a)
        with self.assertRaises(ValidationError):
            self.Order.create({
                'partner_id': self.customer.id, 'site_id': self.site.id,
                'contract_id': c.id, 'asset_id': a.id})

    # ---------- owned & rented-in CAN be rented ----------
    def test_owned_can_be_rented(self):
        a = self._asset(owner_type='owned')
        c = self._contract(a)
        order = self.Order.create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_id': c.id, 'asset_id': a.id})
        self.assertTrue(order)

    def test_switch_to_customer_owned_flips_rentable(self):
        a = self._asset(owner_type='rented_in', owner_partner_id=self.vendor.id)
        self.assertTrue(a.is_rentable)
        a.write({'owner_type': 'customer_owned',
                 'owner_partner_id': self.customer.id})
        self.assertFalse(a.is_rentable)

    def _contract(self, asset):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0})
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c
