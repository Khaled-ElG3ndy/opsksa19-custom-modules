# -*- coding: utf-8 -*-
import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_SIG = base64.b64encode(b'customer-signature-data')


@tagged('post_install', '-at_install')
class TestAllEquipment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Order = cls.env['gr.rental.order']
        cls.Type = cls.env['gr.equipment.type']
        cls.cable_type = cls.env.ref('gr_equipment.equipment_type_cable')
        cls.generator_type = cls.env.ref('gr_equipment.equipment_type_generator')
        cls.panel_type = cls.env.ref('gr_equipment.equipment_type_distribution_panel')
        cls.tank_type = cls.env.ref('gr_equipment.equipment_type_fuel_tank')
        cls.customer = cls.env['res.partner'].create({'name': 'Cable Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Cable Site',
            'partner_id': cls.customer.id,
        })
        cls.gm = cls.env['res.users'].create({
            'name': 'All Equipment GM',
            'login': 'all_equipment_gm',
            'email': 'all.equipment.gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'gr_security_base.group_generator_general_manager').id),
            ],
        })

    def _contract(self):
        contract = self.env['gr.rental.contract'].create({
            'partner_id': self.customer.id,
            'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0,
            'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0,
        })
        contract.action_submit()
        contract.with_user(self.gm).action_approve()
        contract.action_activate()
        return contract

    def _asset(self, code, equipment_type, **extra):
        vals = {
            'code': code,
            'name': extra.pop('name', code),
            'equipment_type_id': equipment_type.id,
            'serial_number': '%s-SN' % code,
            'pm_interval_hours': 0.0,
            'owner_type': 'owned',
        }
        vals.update(extra)
        return self.Asset.create(vals)

    def _cables(self, count=5):
        return self.Asset.browse([
            self._asset(
                'CAB-%03d' % index,
                self.cable_type,
                name='Cable %s m' % (50 if index < 3 else 100),
                specification='Power cable %s m' % (50 if index < 3 else 100),
                length_m=50 if index < 3 else 100,
            ).id
            for index in range(1, count + 1)
        ])

    def _order(self, asset):
        planned_dispatch = fields.Datetime.now() + timedelta(days=1)
        planned_return = planned_dispatch + timedelta(days=7)
        return self.Order.create({
            'partner_id': self.customer.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': asset.id,
            'planned_dispatch_datetime': planned_dispatch,
            'planned_return_datetime': planned_return,
        })

    def _approve_if_needed(self, record):
        if 'approval_state' not in record._fields:
            return
        with patch.object(type(record), '_render_approval_pdf',
                          return_value=b'%PDF-test'):
            if not record.current_approval_document_id:
                record._generate_approval_copy(language='en_US')
            record.approval_signature = _SIG
            record.approval_signed_by = 'Test Customer'
            record.action_approve_by_signature()

    def _confirm(self, order):
        self._approve_if_needed(order)
        order.action_confirm()

    def _pass_delivery_inspection(self, order):
        if 'gr.rental.inspection' not in self.env:
            return
        action = order.action_create_delivery_inspection()
        inspection = self.env['gr.rental.inspection'].browse(action['res_id'])
        self._approve_if_needed(inspection)
        inspection.action_pass()

    def _pass_return_inspection(self, order):
        if 'gr.rental.inspection' not in self.env:
            return
        inspection = order.inspection_ids.filtered(lambda i: i.mode == 'return')[:1]
        if inspection:
            self._approve_if_needed(inspection)
            inspection.action_pass()

    def _sign_return_if_needed(self, order):
        order.invalidate_recordset()
        if order.rental_workflow_requires_return_signature:
            order.customer_return_signature = _SIG

    def _run_to_on_rent(self, order):
        self._confirm(order)
        order.action_reserve()
        if order.rental_workflow_requires_delivery_inspection:
            self._pass_delivery_inspection(order)
        if order.rental_workflow_requires_dispatch:
            order.action_dispatch()
        if order.rental_workflow_requires_installation:
            order.action_install()
        order.action_start_rental()

    def _return_and_close(self, order):
        self._sign_return_if_needed(order)
        order.action_return()
        if order.rental_workflow_requires_return_inspection:
            self._pass_return_inspection(order)
            order.action_start_inspection()
        order.action_close()

    def test_cable_count_available(self):
        self._cables(5)
        domain = [('equipment_type_id', '=', self.cable_type.id)]
        self.assertEqual(self.Asset.search_count(domain), 5)
        self.assertEqual(self.Asset.search_count(
            domain + [('status', '=', 'available')]), 5)

    def test_availability_state_buckets_operational_statuses(self):
        available = self._asset('AVL-BKT-001', self.cable_type)
        reserved = self._asset(
            'RES-BKT-001', self.cable_type, status='reserved')
        on_rent = self._asset(
            'RNT-BKT-001', self.cable_type, status='on_rent')
        maintenance = self._asset(
            'MNT-BKT-001', self.cable_type, status='under_maintenance')
        breakdown = self._asset(
            'BRK-BKT-001', self.cable_type, status='breakdown')
        inspection = self._asset(
            'INS-BKT-001', self.cable_type,
            status='returned_pending_inspection')
        customer_owned = self._asset(
            'CUS-BKT-001', self.cable_type, owner_type='customer_owned',
            owner_partner_id=self.customer.id)

        self.assertEqual(available.availability_state, 'available')
        self.assertEqual(reserved.availability_state, 'rented')
        self.assertEqual(on_rent.availability_state, 'rented')
        self.assertEqual(maintenance.availability_state, 'maintenance')
        self.assertEqual(breakdown.availability_state, 'maintenance')
        self.assertEqual(inspection.availability_state, 'unavailable')
        self.assertEqual(customer_owned.availability_state, 'unavailable')

    def test_equipment_availability_action_is_grouped_by_availability(self):
        action = self.env.ref('gr_equipment.action_gr_equipment_availability')
        menu = self.env.ref('gr_equipment.menu_gr_equipment_availability')

        self.assertEqual(action.res_model, 'gr.generator.asset')
        self.assertIn('search_default_g_availability', action.context)
        self.assertEqual(menu.action, action)

    def test_renting_one_cable_updates_current_fields_and_counts(self):
        cables = self._cables(5)
        cable = cables.filtered(lambda a: a.code == 'CAB-001')
        order = self._order(cable)

        self._run_to_on_rent(order)
        cable.invalidate_recordset()

        self.assertEqual(cable.status, 'on_rent')
        self.assertEqual(cable.availability_state, 'rented')
        self.assertEqual(cable.current_customer_id, self.customer)
        self.assertEqual(cable.current_rental_order_id, order)
        self.assertEqual(self.Asset.search_count([
            ('equipment_type_id', '=', self.cable_type.id),
            ('status', '=', 'available'),
        ]), 4)
        self.assertEqual(self.Asset.search_count([
            ('equipment_type_id', '=', self.cable_type.id),
            ('status', '=', 'on_rent'),
        ]), 1)

    def test_active_cable_cannot_be_double_booked(self):
        cable = self._cables(1)
        order = self._order(cable)
        self._run_to_on_rent(order)

        second = self._order(cable)
        with self.assertRaises(UserError):
            self._confirm(second)

    def test_return_and_pass_inspection_releases_cable(self):
        cable = self._cables(1)
        order = self._order(cable)
        self._run_to_on_rent(order)

        self._return_and_close(order)
        cable.invalidate_recordset()

        self.assertEqual(cable.status, 'available')
        self.assertEqual(cable.availability_state, 'available')
        self.assertFalse(cable.current_customer_id)
        self.assertFalse(cable.current_rental_order_id)

    def test_cable_only_order_completes_lifecycle(self):
        cable = self._cables(1)
        order = self._order(cable)
        self._run_to_on_rent(order)
        self._return_and_close(order)
        self.assertEqual(order.state, 'closed')

    def test_generator_and_cable_are_tracked_independently(self):
        generator = self._asset(
            'GEN-TEST-001',
            self.generator_type,
            name='Generator 100 KVA',
            kva_rating=100,
            pm_interval_hours=2000.0,
        )
        cable = self._cables(1)
        generator_order = self._order(generator)
        cable_order = self._order(cable)

        self._run_to_on_rent(generator_order)
        self._run_to_on_rent(cable_order)
        generator.invalidate_recordset()
        cable.invalidate_recordset()

        self.assertEqual(generator.status, 'on_rent')
        self.assertEqual(cable.status, 'on_rent')
        self.assertEqual(generator.current_rental_order_id, generator_order)
        self.assertEqual(cable.current_rental_order_id, cable_order)

    def test_default_workflow_policy_by_equipment_type(self):
        self.assertTrue(self.generator_type.rental_requires_dispatch)
        self.assertTrue(self.generator_type.rental_requires_installation)
        self.assertTrue(self.generator_type.rental_requires_meter_readings)
        self.assertTrue(self.generator_type.rental_requires_delivery_inspection)
        self.assertTrue(self.generator_type.rental_requires_return_inspection)

        self.assertTrue(self.cable_type.rental_requires_dispatch)
        self.assertFalse(self.cable_type.rental_requires_installation)
        self.assertFalse(self.cable_type.rental_requires_meter_readings)
        self.assertFalse(self.cable_type.rental_requires_delivery_inspection)
        self.assertFalse(self.cable_type.rental_requires_return_inspection)

        self.assertTrue(self.panel_type.rental_requires_installation)
        self.assertFalse(self.panel_type.rental_requires_meter_readings)
        self.assertTrue(self.panel_type.rental_requires_delivery_inspection)

        self.assertTrue(self.tank_type.rental_requires_dispatch)
        self.assertFalse(self.tank_type.rental_requires_installation)
        self.assertFalse(self.tank_type.rental_requires_meter_readings)
        self.assertTrue(self.tank_type.rental_requires_delivery_inspection)

    def test_cable_ui_policy_skips_install_meter_and_inspections(self):
        cable = self._cables(1)
        order = self._order(cable)
        self._confirm(order)
        order.action_reserve()

        self.assertTrue(order.rental_show_dispatch_button)
        self.assertFalse(order.rental_workflow_requires_installation)
        self.assertFalse(order.rental_workflow_requires_meter_readings)
        self.assertFalse(order.rental_workflow_requires_delivery_inspection)
        order.action_dispatch()
        self.assertFalse(order.rental_show_install_button)
        self.assertTrue(order.rental_show_start_rental_button)
        order.action_start_rental()
        self._sign_return_if_needed(order)
        order.action_return()
        self.assertFalse(order.rental_show_start_inspection_button)
        self.assertTrue(order.rental_show_close_button)
        order.action_close()
        self.assertEqual(order.state, 'closed')

    def test_return_signature_required_only_at_return_step(self):
        cable = self._cables(1)
        order = self._order(cable)
        self.assertTrue(order.rental_workflow_requires_return_signature)
        self.assertFalse(order.rental_workflow_return_signature_due)

        self._run_to_on_rent(order)
        self.assertTrue(order.rental_workflow_return_signature_due)
        with self.assertRaises(UserError):
            order.action_return()

        self._sign_return_if_needed(order)
        order.action_return()
        self.assertEqual(order.state, 'returned')

    def test_panel_requires_installation_and_inspections_without_meter(self):
        panel = self._asset('PNL-WF-001', self.panel_type)
        order = self._order(panel)
        self._confirm(order)
        order.action_reserve()
        self._pass_delivery_inspection(order)
        order.action_dispatch()

        self.assertTrue(order.rental_show_install_button)
        self.assertFalse(order.rental_workflow_requires_meter_readings)
        order.action_install()
        order.action_start_rental()
        self._sign_return_if_needed(order)
        order.action_return()
        self._pass_return_inspection(order)
        self.assertTrue(order.rental_show_start_inspection_button)
        order.action_start_inspection()
        order.action_close()
        self.assertEqual(order.state, 'closed')

    def test_tank_requires_inspections_without_installation_or_meter(self):
        tank = self._asset('TNK-WF-001', self.tank_type)
        order = self._order(tank)
        self._confirm(order)
        order.action_reserve()
        self._pass_delivery_inspection(order)
        order.action_dispatch()

        self.assertFalse(order.rental_show_install_button)
        self.assertTrue(order.rental_show_start_rental_button)
        self.assertFalse(order.rental_workflow_requires_meter_readings)
        order.action_start_rental()
        self._sign_return_if_needed(order)
        order.action_return()
        self._pass_return_inspection(order)
        order.action_start_inspection()
        order.action_close()
        self.assertEqual(order.state, 'closed')
