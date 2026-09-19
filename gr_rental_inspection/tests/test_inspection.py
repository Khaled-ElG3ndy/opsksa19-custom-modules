# -*- coding: utf-8 -*-
import base64

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tests import tagged

_SIG = base64.b64encode(b'return-signature-data')


@tagged('post_install', '-at_install')
class TestRentalInspection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Insp = cls.env['gr.rental.inspection']
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.partner = cls.env['res.partner'].create({'name': 'Insp Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Insp Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Insp GM', 'login': 'insp_gm', 'email': 'ig@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})

    def _contract(self):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0})
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _order(self):
        a = self.Asset.create({'name': 'Insp Gen', 'pm_interval_hours': 2000.0})
        o = self.Order.create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_id': self._contract().id, 'asset_id': a.id})
        o.action_confirm(); o.action_reserve()
        return o, a

    # ---------- checklist master data loaded ----------
    def test_checklist_master_seeded(self):
        items = self.env['gr.rental.checklist.item'].search([])
        self.assertGreaterEqual(len(items), 12)
        names = items.mapped('name')
        self.assertIn('Oil level & condition', names)
        self.assertIn('Load conditions', names)

    # ---------- readiness gate ----------
    def test_dispatch_blocked_without_delivery_inspection(self):
        o, a = self._order()
        with self.assertRaises(UserError):
            o.action_dispatch()  # no passed delivery inspection

    def test_dispatch_allowed_after_passed_delivery(self):
        o, a = self._order()
        insp = self.Insp.create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist()
        insp.action_pass()
        self.assertTrue(o.delivery_inspection_passed)
        o.action_dispatch()  # now allowed
        self.assertEqual(o.state, 'dispatched')

    def test_delivery_inspection_prefills_checklist(self):
        o, a = self._order()
        act = o.action_create_delivery_inspection()
        insp = self.Insp.browse(act['res_id'])
        self.assertEqual(insp.mode, 'delivery')
        self.assertGreaterEqual(len(insp.checklist_ids), 12)

    # ---------- pass/fail rules ----------
    def test_failed_item_blocks_pass(self):
        o, a = self._order()
        insp = self.Insp.create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist()
        insp.checklist_ids[0].result = 'fail'
        with self.assertRaises(UserError):
            insp.action_pass()

    def test_can_mark_failed(self):
        o, a = self._order()
        insp = self.Insp.create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp.action_fail()
        self.assertEqual(insp.state, 'failed')

    # ---------- return lock ----------
    def _dispatch_to_on_rent(self):
        o, a = self._order()
        insp = self.Insp.create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); insp.action_pass()
        o.action_dispatch()
        o.start_meter_reading = 0.0
        o.action_install(); o.action_start_rental()
        return o, a

    def _sign_return_if_needed(self, order):
        if 'rental_workflow_requires_return_signature' in order._fields:
            order.invalidate_recordset()
            if order.rental_workflow_requires_return_signature:
                order.customer_return_signature = _SIG

    def test_return_autocreates_return_inspection(self):
        o, a = self._dispatch_to_on_rent()
        o.end_meter_reading = 50.0
        self._sign_return_if_needed(o)
        o.action_return()
        ret = o.inspection_ids.filtered(lambda i: i.mode == 'return')
        self.assertTrue(ret)
        self.assertAlmostEqual(ret.current_hours, 50.0)

    def test_close_blocked_without_return_inspection_pass(self):
        o, a = self._dispatch_to_on_rent()
        o.end_meter_reading = 50.0
        self._sign_return_if_needed(o)
        o.action_return()
        o.action_start_inspection()
        # return inspection exists but not passed -> close blocked
        with self.assertRaises(UserError):
            o.action_close()

    def test_close_allowed_after_return_inspection_pass(self):
        o, a = self._dispatch_to_on_rent()
        o.end_meter_reading = 50.0
        self._sign_return_if_needed(o)
        o.action_return()
        ret = o.inspection_ids.filtered(lambda i: i.mode == 'return')
        ret.action_pass()
        o.action_start_inspection()
        o.action_close()
        self.assertEqual(o.state, 'closed')

    # ---------- sequence ----------
    def test_sequence_generation(self):
        o, a = self._order()
        insp = self.Insp.create({'rental_order_id': o.id, 'mode': 'delivery'})
        self.assertTrue(insp.name.startswith('GR/INSP/'))
