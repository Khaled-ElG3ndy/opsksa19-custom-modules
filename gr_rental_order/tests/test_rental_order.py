# -*- coding: utf-8 -*-
import base64
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.tests import tagged

_SIG = base64.b64encode(b'return-signature-data')


@tagged('post_install', '-at_install')
class TestRentalOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.Contract = cls.env['gr.rental.contract']
        cls.partner = cls.env['res.partner'].create({'name': 'RO Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'RO Site', 'partner_id': cls.partner.id})

    def _gm(self):
        return self.env['res.users'].create({
            'name': 'RO GM', 'login': 'ro_gm_test', 'email': 'ro_gm@example.com',
            'group_ids': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})

    def _approved_contract(self):
        c = self.Contract.create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0})
        c.action_submit()
        c.with_user(self._gm()).action_approve()
        c.action_activate()
        return c

    def _asset(self, **kw):
        vals = {'name': 'RO Gen', 'pm_interval_hours': 250.0, 'current_hour_meter': 0.0}
        vals.update(kw)
        return self.Asset.create(vals)

    def _make_order(self, asset, contract):
        return self.Order.create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_id': contract.id, 'asset_id': asset.id})

    def _approve_order_if_needed(self, order):
        if 'approval_state' not in order._fields:
            return
        with patch.object(type(order), '_render_approval_pdf',
                          return_value=b'%PDF-rental-order-test'):
            if not order.current_approval_document_id:
                order._generate_approval_copy(language='en_US')
            order.approval_signature = _SIG
            order.approval_signed_by = 'Rental Order Tester'
            order.action_approve_by_signature()

    def _confirm(self, order):
        self._approve_order_if_needed(order)
        order.action_confirm()

    def _pass_inspection(self, inspection):
        self._approve_order_if_needed(inspection)
        inspection.action_pass()

    def _sign_return_if_needed(self, order):
        if 'rental_workflow_requires_return_signature' in order._fields:
            order.invalidate_recordset()
            if order.rental_workflow_requires_return_signature:
                order.with_context(
                    skip_customer_approval_lock=True,
                ).customer_return_signature = _SIG

    # ----- sequence -----
    def test_create_assigns_sequence(self):
        o = self._make_order(self._asset(), self._approved_contract())
        self.assertTrue(o.name.startswith('GR/RO/'))

    # ----- confirm requires approved/active contract -----
    def test_confirm_requires_active_contract(self):
        draft_c = self.Contract.create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 1000.0})
        o = self._make_order(self._asset(), draft_c)
        with self.assertRaises(UserError):
            o.action_confirm()  # contract is draft

    # ----- reserve requires available asset -----
    def test_reserve_available_asset(self):
        a = self._asset()
        o = self._make_order(a, self._approved_contract())
        self._confirm(o)
        o.action_reserve()
        self.assertEqual(o.state, 'reserved')
        self.assertEqual(a.status, 'reserved')

    def test_reserve_unavailable_blocked(self):
        a = self._asset(status='under_maintenance')
        o = self._make_order(a, self._approved_contract())
        with self.assertRaises(UserError):
            self._confirm(o)

    # ----- double booking -----
    def test_double_booking_blocked(self):
        a = self._asset()
        c = self._approved_contract()
        o1 = self._make_order(a, c)
        self._confirm(o1)
        o1.action_reserve()  # a now reserved on o1
        # Second order for the same asset
        a.status = 'available'  # force-available to simulate a sneaky attempt
        o2 = self._make_order(a, c)
        self._approve_order_if_needed(o2)
        with self.assertRaises(UserError):
            o2.action_confirm()  # confirmed orders reserve the date range

    # ----- dispatch blocked if maintenance overdue -----
    def test_dispatch_blocked_if_overdue(self):
        # Build an overdue asset realistically: an "available" asset may not be
        # overdue (that asset-level constraint is correct), so we move it to
        # maintenance_due in the same write that pushes the meter past the PM
        # interval. The order's reserve action must then refuse it.
        a = self._asset(pm_interval_hours=100.0, current_hour_meter=0.0)
        a.write({'current_hour_meter': 120.0, 'status': 'maintenance_due'})
        self.assertTrue(a.maintenance_overdue)
        o = self._make_order(a, self._approved_contract())
        with self.assertRaises(UserError):
            self._confirm(o)

    # ----- install requires start meter >= asset meter -----
    def test_install_with_valid_meter(self):
        a = self._asset(current_hour_meter=50.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 50.0
        o.action_install()
        self.assertEqual(o.state, 'installed')
        self.assertEqual(a.status, 'on_rent')
        self.assertEqual(a.current_rental_order_ref, o.name)
        self.assertEqual(a.current_customer_id, self.partner)

    def test_install_lower_meter_blocked(self):
        a = self._asset(current_hour_meter=100.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 90.0
        with self.assertRaises(UserError):
            o.action_install()

    # ----- return requires end meter, updates asset -----
    def test_return_updates_asset(self):
        a = self._asset(current_hour_meter=50.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 50.0
        o.action_install(); o.action_start_rental()
        o.end_meter_reading = 90.0
        self._sign_return_if_needed(o)
        o.action_return()
        a.invalidate_recordset()
        self.assertEqual(o.state, 'returned')
        self.assertEqual(a.status, 'returned_pending_inspection')
        self.assertEqual(a.current_hour_meter, 90.0)

    def test_return_lower_end_meter_blocked(self):
        a = self._asset(current_hour_meter=50.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 50.0
        o.action_install(); o.action_start_rental()
        # The end < start constraint fires on write (ValidationError is a
        # subclass of UserError), so the bad write itself must be guarded.
        with self.assertRaises(UserError):
            o.write({'end_meter_reading': 40.0})

    # ----- close releases asset, but not before inspection -----
    def test_close_requires_inspection(self):
        a = self._asset(current_hour_meter=50.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 50.0
        o.action_install(); o.action_start_rental()
        o.end_meter_reading = 90.0
        self._sign_return_if_needed(o)
        o.action_return()
        ret = o.inspection_ids.filtered(lambda i: i.mode == 'return')
        self._pass_inspection(ret)
        # cannot close directly from returned
        with self.assertRaises(UserError):
            o.action_close()
        o.action_start_inspection()
        o.action_close()
        self.assertEqual(o.state, 'closed')
        self.assertEqual(a.status, 'available')

    # ----- M13 return-lock: close requires a PASSED return inspection -----
    def test_close_requires_passed_return_inspection(self):
        a = self._asset(current_hour_meter=50.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 50.0
        o.action_install(); o.action_start_rental()
        o.end_meter_reading = 90.0
        self._sign_return_if_needed(o)
        o.action_return()
        # return inspection exists but is NOT passed -> close is blocked
        with self.assertRaises(UserError):
            o.action_close()
        ret = o.inspection_ids.filtered(lambda i: i.mode == 'return')
        self._pass_inspection(ret)
        o.action_start_inspection()
        o.action_close()
        self.assertEqual(o.state, 'closed')

    # ----- cancel releases reserved asset -----
    def test_cancel_releases_asset(self):
        a = self._asset()
        o = self._make_order(a, self._approved_contract())
        self._confirm(o); o.action_reserve()
        self.assertEqual(a.status, 'reserved')
        o.action_cancel()
        self.assertEqual(o.state, 'cancelled')
        self.assertEqual(a.status, 'available')

    # ----- full happy path -----
    def test_full_lifecycle(self):
        a = self._asset(current_hour_meter=10.0)
        o = self._make_order(a, self._approved_contract())
        self._confirm(o)
        o.action_reserve()
        insp = self.env['gr.rental.inspection'].create({'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist(); self._pass_inspection(insp)
        o.action_dispatch()
        o.start_meter_reading = 10.0
        o.action_install()
        o.action_start_rental()
        o.action_request_off_hire()
        o.end_meter_reading = 60.0
        self._sign_return_if_needed(o)
        o.action_return()
        ret = o.inspection_ids.filtered(lambda i: i.mode == 'return')
        self._pass_inspection(ret)
        o.action_start_inspection()
        o.action_close()
        self.assertEqual(o.state, 'closed')
        self.assertEqual(a.status, 'available')
        self.assertEqual(a.current_hour_meter, 60.0)

    # ----- meter constraint -----
    def test_end_before_start_constraint(self):
        a = self._asset()
        o = self._make_order(a, self._approved_contract())
        with self.assertRaises(ValidationError):
            o.write({'start_meter_reading': 100.0, 'end_meter_reading': 50.0})
