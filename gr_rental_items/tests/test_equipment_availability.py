# -*- coding: utf-8 -*-
import base64
from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


_SIG = base64.b64encode(b'availability-signature')


@tagged('post_install', '-at_install')
class TestEquipmentAvailability(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Asset = cls.env['gr.generator.asset']
        cls.Order = cls.env['gr.rental.order']
        cls.Line = cls.env['gr.rental.order.line']
        cls.Availability = cls.env['gr.rental.availability']
        cls.partner = cls.env['res.partner'].create({'name': 'Availability Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Availability Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Availability GM',
            'login': 'availability_gm',
            'email': 'availability_gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref(
                    'gr_security_base.group_generator_general_manager').id),
            ],
        })
        cls.generator_type = cls.env.ref('gr_equipment.equipment_type_generator')
        cls.cable_type = cls.env.ref('gr_equipment.equipment_type_cable')

    def _contract(self):
        contract = self.env['gr.rental.contract'].create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0,
            'max_hours_per_day': 12.0,
            'base_daily_rate': 700.0,
        })
        contract.action_submit()
        contract.with_user(self.gm).action_approve()
        contract.action_activate()
        return contract

    def _asset(self, name, equipment_type=False, **extra):
        vals = {
            'name': name,
            'equipment_type_id': (equipment_type or self.generator_type).id,
            'owner_type': 'owned',
            'pm_interval_hours': 0.0,
        }
        vals.update(extra)
        return self.Asset.create(vals)

    def _order(self, asset, start, end):
        return self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': asset.id if asset else False,
            'date_requested': start,
            'planned_dispatch_datetime': start,
            'planned_return_datetime': end,
        })

    def _approve_if_needed(self, order):
        if 'approval_state' not in order._fields:
            return
        with patch.object(type(order), '_render_approval_pdf',
                          return_value=b'%PDF-availability'):
            if not order.current_approval_document_id:
                order._generate_approval_copy(language='en_US')
            order.approval_signature = _SIG
            order.approval_signed_by = 'Availability Tester'
            order.action_approve_by_signature()

    def _confirm(self, order):
        self._approve_if_needed(order)
        order.action_confirm()

    def _commit_as_on_rent(self, order):
        self._confirm(order)
        order.with_context(skip_customer_approval_lock=True).write({
            'state': 'on_rent',
        })
        if order.asset_id:
            order.asset_id.status = 'on_rent'
        return order

    def test_confirmed_order_reserves_the_date_range(self):
        asset = self._asset('AV-GEN-001')
        first = self._order(
            asset, datetime(2026, 9, 1, 8, 0, 0),
            datetime(2026, 9, 10, 8, 0, 0))
        self._confirm(first)

        second = self.Order.create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': asset.id,
            'date_requested': datetime(2026, 9, 5, 8, 0, 0),
            'planned_dispatch_datetime': datetime(2026, 9, 5, 8, 0, 0),
            'planned_return_datetime': datetime(2026, 9, 7, 8, 0, 0),
        })
        self._approve_if_needed(second)
        with self.assertRaises(UserError):
            second.action_confirm()
        self.assertEqual(second.state, 'draft')

    def test_future_non_overlapping_reservation_keeps_current_status(self):
        asset = self._asset('AV-GEN-002')
        current = self._order(
            asset, datetime(2026, 8, 1, 8, 0, 0),
            datetime(2026, 8, 15, 8, 0, 0))
        current.with_context(skip_customer_approval_lock=True).write({
            'state': 'on_rent',
        })
        asset.status = 'on_rent'

        future = self._order(
            asset, datetime(2026, 8, 16, 8, 0, 0),
            datetime(2026, 8, 20, 8, 0, 0))
        self._confirm(future)
        future.action_reserve()

        self.assertEqual(future.state, 'reserved')
        self.assertEqual(
            asset.status, 'on_rent',
            "future reservations must not overwrite today's operational status")

    def test_non_primary_line_asset_conflict_is_blocked(self):
        generator = self._asset('AV-GEN-003')
        cable = self._asset('AV-CABLE-001', self.cable_type)
        first = self._order(
            generator, datetime(2026, 9, 1, 8, 0, 0),
            datetime(2026, 9, 10, 8, 0, 0))
        self.Line.create({
            'order_id': first.id,
            'equipment_asset_id': cable.id,
        })
        self._confirm(first)
        first.action_reserve()

        second = self._order(
            self._asset('AV-GEN-004'), datetime(2026, 9, 5, 8, 0, 0),
            datetime(2026, 9, 8, 8, 0, 0))
        self.Line.create({
            'order_id': second.id,
            'equipment_asset_id': cable.id,
        })
        self._approve_if_needed(second)
        with self.assertRaises(UserError):
            second.action_confirm()

    def test_available_assets_uses_datetime_overlap_not_status_only(self):
        asset = self._asset('AV-GEN-005')
        order = self._order(
            asset, datetime(2026, 9, 1, 8, 0, 0),
            datetime(2026, 9, 10, 8, 0, 0))
        self._confirm(order)

        available = self.Availability.available_assets(
            datetime(2026, 9, 10, 8, 0, 0),
            datetime(2026, 9, 12, 8, 0, 0),
            self.env.company,
            domain=[('id', '=', asset.id)],
        )
        self.assertIn(asset, available)

        blocked = self.Availability.available_assets(
            datetime(2026, 9, 9, 8, 0, 0),
            datetime(2026, 9, 12, 8, 0, 0),
            self.env.company,
            domain=[('id', '=', asset.id)],
        )
        self.assertNotIn(asset, blocked)

    def _asset_selector_arches(self):
        order_arch = self.Order.get_view(
            self.env.ref('gr_rental_order.view_gr_rental_order_form').id,
            'form')['arch']
        line_arch = self.Order.get_view(
            self.env.ref('gr_rental_items.view_gr_rental_order_form_items').id,
            'form')['arch']
        return order_arch, line_arch

    def test_asset_dropdowns_use_simple_current_available_status_domain(self):
        order_arch, line_arch = self._asset_selector_arches()
        self.assertIn("domain=\"[('status', '=', 'available')]\"", order_arch)
        self.assertIn("domain=\"[('status', '=', 'available')]\"", line_arch)
        self.assertNotIn('available_rental_asset_ids', order_arch)
        self.assertNotIn('available_equipment_asset_ids', line_arch)
        self.assertNotIn('parent.available_rental_asset_ids', line_arch)

        main_domain = self.Order._fields['asset_id'].domain
        line_domain = self.Line._fields['equipment_asset_id'].domain
        self.assertEqual(main_domain, "[('status', '=', 'available')]")
        self.assertEqual(line_domain, "[('status', '=', 'available')]")

    def test_asset_dropdown_status_domain_available_asset_appears(self):
        available = self._asset('AV-STATUS-AVAILABLE', status='available')
        self.assertIn(available, self.Asset.search([('status', '=', 'available')]))

    def test_asset_dropdown_status_domain_rented_asset_hidden(self):
        rented = self._asset('AV-STATUS-ON-RENT', status='on_rent')
        self.assertNotIn(rented, self.Asset.search([('status', '=', 'available')]))

    def test_asset_dropdown_status_domain_damaged_asset_hidden(self):
        damaged = self._asset('AV-STATUS-DAMAGED', status='breakdown')
        self.assertNotIn(damaged, self.Asset.search([('status', '=', 'available')]))

    def test_asset_dropdown_status_domain_returned_pending_inspection_hidden(self):
        pending = self._asset(
            'AV-STATUS-PENDING-INSPECTION',
            status='returned_pending_inspection')
        self.assertNotIn(pending, self.Asset.search([('status', '=', 'available')]))

    def test_asset_dropdown_status_domain_available_third_party_appears(self):
        supplier = self.env['res.partner'].create({'name': 'Status Supplier'})
        third_party = self._asset(
            'AV-STATUS-THIRD-PARTY',
            owner_type='rented_in',
            owner_partner_id=supplier.id,
            status='available')
        self.assertIn(third_party, self.Asset.search([('status', '=', 'available')]))

    def test_backend_validation_still_rejects_dropdown_bypass(self):
        asset = self._asset('AV-BYPASS-B')
        reserved = self._order(
            asset, datetime(2026, 8, 12, 8, 0, 0),
            datetime(2026, 8, 15, 8, 0, 0))
        self._confirm(reserved)

        bypass = self._order(
            asset, datetime(2026, 8, 12, 8, 0, 0),
            datetime(2026, 8, 14, 8, 0, 0))
        self._approve_if_needed(bypass)
        with self.assertRaises(UserError):
            bypass.action_confirm()
