# -*- coding: utf-8 -*-
import base64
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

_SIG = base64.b64encode(b'customer-signature-data')


@tagged('post_install', '-at_install')
class TestRentalItems(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Type = cls.env['gr.rental.item.type']
        cls.Unit = cls.env['gr.rental.item.unit']
        cls.Line = cls.env['gr.rental.order.line']
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.partner = cls.env['res.partner'].create({'name': 'Item Cust'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Item Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Item GM', 'login': 'item_gm', 'email': 'igm@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id),
                          (4, cls.env.ref('gr_security_base.group_generator_general_manager').id)]})
        cls.cable_type = cls.env.ref('gr_rental_items.item_type_cable')
        cls.panel_type = cls.env.ref('gr_rental_items.item_type_distribution_panel')
        cls.equipment_type_generator = cls.env.ref('gr_equipment.equipment_type_generator')
        cls.equipment_type_cable = cls.env.ref('gr_equipment.equipment_type_cable')
        cls.equipment_type_tank = cls.env.ref('gr_equipment.equipment_type_fuel_tank')
        cls.equipment_type_panel = cls.env.ref('gr_equipment.equipment_type_distribution_panel')

    def _contract(self):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0})
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _unit(self, item_type, spec='spec'):
        return self.Unit.create({'item_type_id': item_type.id, 'specification': spec})

    def _equipment_asset(self, equipment_type, code, **extra):
        vals = {
            'name': code,
            'code': code,
            'equipment_type_id': equipment_type.id,
            'serial_number': '%s-SN' % code,
            'pm_interval_hours': 0.0,
            'owner_type': 'owned',
        }
        vals.update(extra)
        return self.Asset.create(vals)

    def _order(self, with_generator=True):
        vals = {'partner_id': self.partner.id, 'site_id': self.site.id,
                'contract_id': self._contract().id}
        if with_generator:
            vals['asset_id'] = self.Asset.create({
                'name': 'Item Gen', 'pm_interval_hours': 2000.0}).id
        return self.Order.create(vals)

    def _approve_order_if_needed(self, order):
        if 'approval_state' not in order._fields:
            return
        with patch.object(type(order), '_render_approval_pdf',
                          return_value=b'%PDF-test'):
            if not order.current_approval_document_id:
                order._generate_approval_copy(language='en_US')
            order.approval_signature = _SIG
            order.approval_signed_by = 'Test Customer'
            order.action_approve_by_signature()

    def _confirm(self, order):
        self._approve_order_if_needed(order)
        order.action_confirm()

    def _pass_delivery_if_needed(self, order):
        if not getattr(order, 'rental_workflow_requires_delivery_inspection', False):
            return
        action = order.action_create_delivery_inspection()
        inspection = self.env['gr.rental.inspection'].browse(action['res_id'])
        self._approve_order_if_needed(inspection)
        inspection.action_pass()

    def _pass_return_if_needed(self, order):
        if not getattr(order, 'rental_workflow_requires_return_inspection', False):
            return
        inspection = order.inspection_ids.filtered(lambda i: i.mode == 'return')[:1]
        if inspection:
            self._approve_order_if_needed(inspection)
            inspection.action_pass()

    def _sign_return_if_needed(self, order):
        order.invalidate_recordset()
        if getattr(order, 'rental_workflow_requires_return_signature', False):
            order.with_context(
                skip_customer_approval_lock=True,
            ).customer_return_signature = _SIG

    # ---------- catalogue ----------
    def test_seeded_item_types(self):
        names = self.Type.search([]).mapped('name')
        self.assertIn('Cable', names)
        self.assertIn('Fuel Tank', names)
        self.assertIn('Distribution Panel', names)

    def test_client_can_add_new_type(self):
        t = self.Type.create({'name': 'Load Bank', 'code': 'LDB',
                              'default_daily_rate': 300.0})
        self.assertEqual(t.default_daily_rate, 300.0)

    def test_unit_sequence(self):
        u = self._unit(self.cable_type)
        self.assertTrue(u.name.startswith('GR/ITM/'))

    # ---------- bundled with a generator ----------
    def test_item_bundled_with_generator(self):
        o = self._order(with_generator=True)
        u = self._unit(self.cable_type, '4-core 120mm 50m')
        line = self.Line.create({
            'order_id': o.id, 'item_type_id': self.cable_type.id,
            'item_unit_id': u.id, 'is_free': True})
        o.invalidate_recordset()
        self.assertTrue(o.has_generator)
        self.assertFalse(o.is_items_only)
        self.assertEqual(o.item_line_count, 2)
        self.assertEqual(line.line_total, 0.0)
        self.assertEqual(o.items_total, 0.0)

    def test_item_priced_line(self):
        o = self._order(with_generator=True)
        u = self._unit(self.panel_type)
        line = self.Line.create({
            'order_id': o.id, 'item_type_id': self.panel_type.id,
            'item_unit_id': u.id, 'daily_rate': 200.0, 'quantity_days': 3.0})
        self.assertAlmostEqual(line.line_total, 600.0)
        o.invalidate_recordset()
        self.assertAlmostEqual(o.items_total, 600.0)

    def test_free_overrides_rate(self):
        o = self._order()
        u = self._unit(self.cable_type)
        line = self.Line.create({
            'order_id': o.id, 'item_type_id': self.cable_type.id,
            'item_unit_id': u.id, 'is_free': True,
            'daily_rate': 100.0, 'quantity_days': 5.0})
        self.assertEqual(line.line_total, 0.0)

    def test_negative_rate_blocked(self):
        o = self._order()
        u = self._unit(self.cable_type)
        with self.assertRaises(ValidationError):
            self.Line.create({'order_id': o.id, 'item_type_id': self.cable_type.id,
                              'item_unit_id': u.id, 'daily_rate': -10.0})

    # ---------- STANDALONE: items with NO generator (the key requirement) ----------
    def test_standalone_flags(self):
        o = self._order(with_generator=False)
        u = self._unit(self.panel_type)
        self.Line.create({
            'order_id': o.id, 'item_type_id': self.panel_type.id,
            'item_unit_id': u.id, 'daily_rate': 250.0, 'quantity_days': 2.0})
        o.invalidate_recordset()
        self.assertFalse(o.has_generator)
        self.assertTrue(o.is_items_only)
        self.assertAlmostEqual(o.items_total, 500.0)

    def test_standalone_full_lifecycle(self):
        """A cable/panel-only rental must run end to end with NO generator."""
        o = self._order(with_generator=False)
        u = self._unit(self.panel_type)
        self.Line.create({'order_id': o.id, 'item_type_id': self.panel_type.id,
                          'item_unit_id': u.id, 'daily_rate': 250.0})
        self._confirm(o)
        self.assertEqual(o.state, 'confirmed')
        o.action_reserve()          # base would have raised "Select a generator"
        self.assertEqual(o.state, 'reserved')
        u.invalidate_recordset()
        self.assertEqual(u.status, 'on_rent')
        o.action_dispatch()         # bypasses M13 delivery-inspection gate
        self.assertEqual(o.state, 'dispatched')
        if o.rental_workflow_requires_installation:
            o.action_install()
        o.action_start_rental()
        self.assertEqual(o.state, 'on_rent')
        self._sign_return_if_needed(o)
        o.action_return()
        self._pass_return_if_needed(o)
        if o.rental_workflow_requires_return_inspection:
            o.action_start_inspection()
        o.action_close()            # bypasses M13 return-inspection gate
        self.assertEqual(o.state, 'closed')
        u.invalidate_recordset()
        self.assertEqual(u.status, 'available')

    def test_order_must_rent_something(self):
        o = self._order(with_generator=False)   # no generator, no items
        with self.assertRaises(UserError):
            self._confirm(o)

    # ---------- no double-booking of an item unit ----------
    def test_item_not_double_booked(self):
        u = self._unit(self.cable_type)
        o1 = self._order(with_generator=False)
        self.Line.create({'order_id': o1.id, 'item_type_id': self.cable_type.id,
                          'item_unit_id': u.id, 'daily_rate': 50.0})
        self._confirm(o1); o1.action_reserve()   # unit now committed

        o2 = self._order(with_generator=False)
        self.Line.create({'order_id': o2.id, 'item_type_id': self.cable_type.id,
                          'item_unit_id': u.id, 'daily_rate': 50.0})
        with self.assertRaises(UserError):
            self._confirm(o2)

    def test_unavailable_item_blocked(self):
        u = self._unit(self.panel_type)
        u.status = 'maintenance'
        o = self._order(with_generator=False)
        self.Line.create({'order_id': o.id, 'item_type_id': self.panel_type.id,
                          'item_unit_id': u.id, 'daily_rate': 100.0})
        with self.assertRaises(UserError):
            self._confirm(o)

    # ---------- unit status follows the order ----------
    def test_unit_status_on_cancel(self):
        o = self._order(with_generator=False)
        u = self._unit(self.panel_type)
        self.Line.create({'order_id': o.id, 'item_type_id': self.panel_type.id,
                          'item_unit_id': u.id, 'daily_rate': 100.0})
        self._confirm(o); o.action_reserve()
        o.action_cancel()
        u.invalidate_recordset()
        self.assertEqual(u.status, 'available')

    # ---------- generator order still works normally (no regression) ----------
    def test_generator_order_unaffected(self):
        o = self._order(with_generator=True)
        self.assertEqual(o.item_line_count, 1)
        self.assertTrue(o.item_line_ids.is_primary_asset_line)
        self.assertEqual(o.item_line_ids.equipment_asset_id, o.asset_id)
        self._confirm(o); o.action_reserve()
        self.assertEqual(o.state, 'reserved')

    # ---------- preferred path: actual Equipment assets as rental lines ----------
    def test_equipment_asset_line_gets_own_default_price(self):
        """Any Asset can be rented as a priced line, not just item-unit records."""
        o = self._order(with_generator=False)
        panel = self._equipment_asset(
            self.equipment_type_panel, 'PNL-LINE-001',
            rental_daily_rate=275.0, specification='400A panel')
        line = self.Line.create({
            'order_id': o.id,
            'equipment_asset_id': panel.id,
            'quantity_days': 2.0,
        })
        self.assertEqual(line.asset_type_display_name, 'Distribution Panel')
        self.assertEqual(line.daily_rate, 275.0)
        self.assertAlmostEqual(line.line_total, 550.0)
        self.assertEqual(line.asset_display_name, panel.display_name)
        self.assertEqual(o.asset_id, panel)
        self.assertTrue(line.is_primary_asset_line)

    def test_single_serial_entered_in_lines_syncs_hidden_primary_asset(self):
        """Users enter even a single generator in the one rental-lines table."""
        o = self._order(with_generator=False)
        gen = self._equipment_asset(
            self.equipment_type_generator, 'GEN-ONLY-LINE-001',
            rental_daily_rate=500.0)
        line = self.Line.create({
            'order_id': o.id,
            'equipment_asset_id': gen.id,
        })
        o.invalidate_recordset()
        self.assertEqual(o.asset_id, gen)
        self.assertTrue(line.is_primary_asset_line)
        self.assertTrue(o.has_generator)
        self.assertEqual(o.generator_serial_count, 1)
        self._confirm(o)
        o.action_reserve()
        gen.invalidate_recordset()
        self.assertEqual(gen.status, 'reserved')

    def test_multiple_generator_serial_lines_count_as_generator(self):
        """Multiple generator serials can live on one order as rental lines."""
        o = self._order(with_generator=False)
        gen1 = self._equipment_asset(
            self.equipment_type_generator, 'GEN-LINE-001',
            rental_daily_rate=500.0)
        gen2 = self._equipment_asset(
            self.equipment_type_generator, 'GEN-LINE-002',
            rental_daily_rate=550.0)
        self.Line.create([
            {'order_id': o.id, 'equipment_asset_id': gen1.id},
            {'order_id': o.id, 'equipment_asset_id': gen2.id},
        ])
        o.invalidate_recordset()
        self.assertTrue(o.has_generator)
        self.assertFalse(o.is_items_only)
        self.assertEqual(o.generator_serial_count, 2)
        self._confirm(o)
        o.action_reserve()
        self.assertEqual(o.state, 'reserved')
        gen1.invalidate_recordset()
        gen2.invalidate_recordset()
        self.assertEqual(gen1.status, 'reserved')
        self.assertEqual(gen2.status, 'reserved')

    def test_additional_generator_line_allowed_with_primary_generator(self):
        """A second generator serial is not treated like a blocked accessory."""
        o = self._order(with_generator=True)
        extra_gen = self._equipment_asset(
            self.equipment_type_generator, 'GEN-EXTRA-001',
            rental_daily_rate=525.0)
        line = self.Line.create({
            'order_id': o.id,
            'equipment_asset_id': extra_gen.id,
        })
        o.invalidate_recordset()
        self.assertEqual(line.equipment_asset_id, extra_gen)
        self.assertTrue(o.has_generator)
        self.assertEqual(o.generator_serial_count, 2)
        self._confirm(o)
        o.action_reserve()
        extra_gen.invalidate_recordset()
        self.assertEqual(extra_gen.status, 'reserved')

    def test_equipment_asset_line_can_be_free_with_generator(self):
        o = self._order(with_generator=True)
        cable = self._equipment_asset(
            self.equipment_type_cable, 'CBL-FREE-001',
            rental_daily_rate=60.0,
            default_is_free_with_asset=True)
        line = self.Line.create({
            'order_id': o.id,
            'equipment_asset_id': cable.id,
            'quantity_days': 5.0,
        })
        self.assertTrue(line.is_free)
        self.assertEqual(line.line_total, 0.0)

    def test_cable_tank_and_panel_assets_rent_standalone(self):
        """Cable-only, tank-only, and panel-only orders need no generator."""
        scenarios = [
            (self.equipment_type_cable, 'CBL-ONLY-001'),
            (self.equipment_type_tank, 'TNK-ONLY-001'),
            (self.equipment_type_panel, 'PNL-ONLY-002'),
        ]
        for equipment_type, code in scenarios:
            asset = self._equipment_asset(
                equipment_type, code, rental_daily_rate=125.0)
            order = self._order(with_generator=False)
            self.Line.create({
                'order_id': order.id,
                'equipment_asset_id': asset.id,
            })
            self._confirm(order)
            order.action_reserve()
            self.assertEqual(order.state, 'reserved')
            asset.invalidate_recordset()
            self.assertEqual(asset.status, 'reserved')
            self._pass_delivery_if_needed(order)
            order.action_dispatch()
            asset.invalidate_recordset()
            self.assertEqual(asset.status, 'in_transit')
            if order.rental_workflow_requires_installation:
                order.action_install()
            order.action_start_rental()
            asset.invalidate_recordset()
            self.assertEqual(asset.status, 'on_rent')
            self._sign_return_if_needed(order)
            order.action_return()
            asset.invalidate_recordset()
            self.assertEqual(asset.status, 'returned_pending_inspection')
            self._pass_return_if_needed(order)
            if order.rental_workflow_requires_return_inspection:
                order.action_start_inspection()
            order.action_close()
            asset.invalidate_recordset()
            self.assertEqual(asset.status, 'available')

    def test_equipment_asset_line_double_booking_against_primary_asset(self):
        cable = self._equipment_asset(
            self.equipment_type_cable, 'CBL-PRIMARY-001')
        primary_order = self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': cable.id,
        })
        self._confirm(primary_order)
        primary_order.action_reserve()
        cable.status = 'available'  # simulate a forced status edit

        line_order = self._order(with_generator=False)
        self.Line.create({
            'order_id': line_order.id,
            'equipment_asset_id': cable.id,
        })
        with self.assertRaises(UserError):
            self._confirm(line_order)
