# -*- coding: utf-8 -*-
import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_SIG = base64.b64encode(b'asset-history-signature')


@tagged('post_install', '-at_install')
class TestAssetHistory(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Order = cls.env['gr.rental.order']
        cls.Contract = cls.env['gr.rental.contract']
        cls.History = cls.env['rental.asset.history']
        cls.RentalHistory = cls.env['rental.asset.rental.history']
        cls.partner = cls.env['res.partner'].create({'name': 'History Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'History Site',
            'partner_id': cls.partner.id,
        })
        cls.gm = cls.env['res.users'].create({
            'name': 'History GM',
            'login': 'history_gm',
            'email': 'history_gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ],
        })
        cls.item_type = cls.env.ref('gr_rental_items.item_type_cable')
        cls.generator_type = cls.env.ref('gr_equipment.equipment_type_generator')
        cls.cable_equipment_type = cls.env.ref('gr_equipment.equipment_type_cable')

    def _contract(self):
        contract = self.Contract.create({
            'partner_id': self.partner.id,
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

    def _asset(self, equipment_type=False, **extra):
        vals = {
            'name': extra.pop('name', 'History Generator'),
            'pm_interval_hours': extra.pop('pm_interval_hours', 2000.0),
            'current_hour_meter': extra.pop('current_hour_meter', 0.0),
            'equipment_type_id': (equipment_type or self.generator_type).id,
            'owner_type': 'owned',
        }
        vals.update(extra)
        return self.Asset.create({
            **vals,
        })

    def _approve_if_needed(self, record):
        if 'approval_state' not in record._fields:
            return
        with patch.object(type(record), '_render_approval_pdf',
                          return_value=b'%PDF-asset-history-test'):
            if not record.current_approval_document_id:
                record._generate_approval_copy(language='en_US')
            record.approval_signature = _SIG
            record.approval_signed_by = 'History Customer'
            record.action_approve_by_signature()

    def _confirm(self, order):
        self._approve_if_needed(order)
        order.action_confirm()

    def test_generator_lifecycle_writes_structured_history(self):
        asset = self._asset()
        contract = self._contract()
        order = self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': contract.id,
            'asset_id': asset.id,
            'planned_return_datetime': fields.Datetime.now() + timedelta(days=7),
        })
        self._confirm(order)
        order.action_reserve()
        inspection = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id,
            'mode': 'delivery',
        })
        inspection._populate_default_checklist()
        self._approve_if_needed(inspection)
        inspection.action_pass()
        order.action_dispatch()
        order.start_meter_reading = 0.0
        order.action_install()
        order.action_start_rental()
        extended_to = order.planned_return_datetime + timedelta(days=3)
        order.with_context(skip_customer_approval_lock=True).write({
            'planned_return_datetime': extended_to,
        })

        asset.invalidate_recordset()
        event_types = set(asset.history_ids.mapped('event_type'))
        self.assertIn('asset_created', event_types)
        self.assertIn('rental_confirmed', event_types)
        self.assertIn('asset_reserved', event_types)
        self.assertIn('delivery', event_types)
        self.assertIn('installed', event_types)
        self.assertIn('rental_started', event_types)
        self.assertIn('rental_extended', event_types)
        self.assertNotIn('status_changed', event_types)
        self.assertNotIn('asset_updated', event_types)
        self.assertEqual(asset.current_presence_type, 'customer')
        self.assertEqual(asset.current_rental_order_id, order)
        self.assertEqual(asset.current_contract_id, contract)
        self.assertEqual(asset.current_site_id, self.site)
        self.assertEqual(asset.expected_return_datetime, extended_to)
        rental_line = self.RentalHistory.search([
            ('asset_id', '=', asset.id),
            ('rental_order_id', '=', order.id),
            ('asset_role', '=', 'main'),
        ])
        self.assertEqual(len(rental_line), 1)
        self.assertEqual(rental_line.partner_id, self.partner)
        self.assertEqual(rental_line.contract_id, contract)
        self.assertGreater(rental_line.duration_days, 0.0)

        before = self.History.search_count([('asset_id', '=', asset.id)])
        self.History.record_event(
            asset,
            event_type='asset_reserved',
            name='Duplicate reservation probe',
            technical_key='gr.rental.order:%s:asset_reserved:asset:%s' % (
                order.id, asset.id),
            source=order,
        )
        after = self.History.search_count([('asset_id', '=', asset.id)])
        self.assertEqual(before, after)

    def test_equipment_asset_line_standalone_history_and_no_duplicate(self):
        cable = self._asset(
            self.cable_equipment_type,
            name='History Cable',
            rental_daily_rate=35.0,
            specification='4-core 50m')
        order = self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'planned_return_datetime': fields.Datetime.now() + timedelta(days=3),
        })
        line = self.env['gr.rental.order.line'].create({
            'order_id': order.id,
            'equipment_asset_id': cable.id,
            'daily_rate': 35.0,
            'quantity_days': 3.0,
        })
        self._confirm(order)
        order.action_reserve()
        order.action_dispatch()
        order.action_start_rental()
        if order.rental_workflow_requires_return_signature:
            order.customer_return_signature = _SIG
        order.action_return()
        order.action_close()

        rental_line = self.RentalHistory.search([
            ('asset_id', '=', cable.id),
            ('rental_order_id', '=', order.id),
            ('order_line_id', '=', line.id),
        ])
        self.assertEqual(len(rental_line), 1)
        self.assertEqual(rental_line.asset_role, 'accessory')
        self.assertEqual(rental_line.revenue_amount, 105.0)
        before = self.RentalHistory.search_count([('asset_id', '=', cable.id)])
        self.RentalHistory.sync_from_order(order)
        self.RentalHistory.sync_from_order(order)
        after = self.RentalHistory.search_count([('asset_id', '=', cable.id)])
        self.assertEqual(before, after)

    def test_free_cable_with_generator_is_accessory_history(self):
        generator = self._asset(name='History Bundle Generator')
        cable = self._asset(
            self.cable_equipment_type,
            name='History Free Cable',
            rental_daily_rate=50.0,
            default_is_free_with_asset=True)
        order = self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': generator.id,
            'planned_return_datetime': fields.Datetime.now() + timedelta(days=2),
        })
        self.env['gr.rental.order.line'].create({
            'order_id': order.id,
            'equipment_asset_id': cable.id,
            'daily_rate': 50.0,
            'quantity_days': 2.0,
            'is_free': True,
        })
        self._confirm(order)
        order.action_reserve()
        inspection = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id,
            'mode': 'delivery',
        })
        inspection._populate_default_checklist()
        self._approve_if_needed(inspection)
        inspection.action_pass()
        order.action_dispatch()
        order.start_meter_reading = 0.0
        order.action_install()
        order.action_start_rental()

        rental_line = self.RentalHistory.search([
            ('asset_id', '=', cable.id),
            ('rental_order_id', '=', order.id),
        ])
        self.assertEqual(len(rental_line), 1)
        self.assertEqual(rental_line.asset_role, 'accessory')
        self.assertTrue(rental_line.is_free)
        self.assertEqual(rental_line.revenue_amount, 0.0)
        self.assertIn('inspection_passed', set(cable.history_ids.mapped('event_type')))

    def test_maintenance_appears_in_asset_summary(self):
        asset = self._asset(name='History Maintenance Asset')
        job = self.env['gr.maintenance.job'].create({
            'asset_id': asset.id,
            'job_type': 'breakdown',
            'work_performed': 'Repaired fuel leak',
        })
        job.action_start()
        job.action_complete()

        asset.invalidate_recordset()
        self.assertEqual(asset.history_last_maintenance_id, job)
        self.assertEqual(asset.history_breakdown_count, 1)
        event_types = set(asset.history_ids.mapped('event_type'))
        self.assertIn('maintenance_opened', event_types)
        self.assertIn('maintenance_started', event_types)
        self.assertIn('maintenance_done', event_types)

    def test_rentable_item_lifecycle_has_own_history(self):
        item = self.env['gr.rental.item.unit'].create({
            'item_type_id': self.item_type.id,
            'specification': '4-core 50m',
        })
        order = self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
        })
        self.env['gr.rental.order.line'].create({
            'order_id': order.id,
            'item_type_id': self.item_type.id,
            'item_unit_id': item.id,
            'daily_rate': 25.0,
        })
        self._confirm(order)
        order.action_reserve()
        item.invalidate_recordset()
        self.assertEqual(item.current_presence_type, 'reserved')
        order.action_dispatch()
        item.invalidate_recordset()
        self.assertEqual(item.current_presence_type, 'transit')
        order.action_install()
        order.action_start_rental()

        item.invalidate_recordset()
        event_types = set(item.history_ids.mapped('event_type'))
        self.assertIn('asset_created', event_types)
        self.assertIn('rental_confirmed', event_types)
        self.assertIn('asset_reserved', event_types)
        self.assertIn('delivery', event_types)
        self.assertIn('installed', event_types)
        self.assertIn('rental_started', event_types)
        self.assertNotIn('status_changed', event_types)
        self.assertNotIn('asset_updated', event_types)
        self.assertEqual(item.current_presence_type, 'customer')
        self.assertEqual(item.current_partner_id, self.partner)
        self.assertEqual(item.current_rental_order_id, order)

    def test_sublet_direct_cost_writes_history(self):
        vendor = self.env['res.partner'].create({'name': 'History Vendor'})
        asset = self.Asset.create({
            'name': 'History Rented-in Generator',
            'pm_interval_hours': 2000.0,
            'current_hour_meter': 0.0,
            'owner_type': 'rented_in',
            'owner_partner_id': vendor.id,
        })
        agreement = self.env['gr.sublet.agreement'].create({
            'asset_id': asset.id,
            'vendor_id': vendor.id,
            'rent_in_amount': 1000.0,
        })
        cost = self.env['gr.sublet.direct.cost'].create({
            'agreement_id': agreement.id,
            'cost_type': 'repair',
            'name': 'Oil hose repair',
            'amount': 120.0,
        })

        event = self.History.search([
            ('asset_id', '=', asset.id),
            ('event_type', '=', 'sublet_direct_cost'),
            ('sublet_direct_cost_id', '=', cost.id),
        ])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.partner_id, vendor)
