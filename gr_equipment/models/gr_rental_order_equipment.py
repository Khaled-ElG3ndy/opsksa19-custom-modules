# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrRentalOrderEquipment(models.Model):
    """Keep customer-owned equipment out of the rental pool: hidden from
    selection via a domain, and hard-blocked server-side as a safety net."""
    _inherit = 'gr.rental.order'

    _ACTIVE_ASSET_STATES = (
        'reserved', 'dispatched', 'installed', 'on_rent',
        'off_hire_requested', 'returned', 'inspection')

    # Narrow the asset selection to rentable (Owned / Rented-in) units only.
    asset_id = fields.Many2one(
        string='Primary Rental Serial',
        domain="[('status', '=', 'available')]",
        help="Technical mirror of the first rental line for legacy workflows. "
             "Users enter all rented serials in the Rented Serials tab.")
    rental_workflow_requires_dispatch = fields.Boolean(
        string='Requires Dispatch / Delivery',
        compute='_compute_rental_workflow_policy')
    rental_workflow_requires_installation = fields.Boolean(
        string='Requires Installation',
        compute='_compute_rental_workflow_policy')
    rental_workflow_requires_meter_readings = fields.Boolean(
        string='Requires Meter Readings',
        compute='_compute_rental_workflow_policy')
    rental_workflow_requires_delivery_inspection = fields.Boolean(
        string='Requires Delivery Inspection',
        compute='_compute_rental_workflow_policy')
    rental_workflow_requires_return_inspection = fields.Boolean(
        string='Requires Return Inspection',
        compute='_compute_rental_workflow_policy')
    rental_workflow_requires_delivery_signature = fields.Boolean(
        string='Requires Delivery Signature',
        compute='_compute_rental_workflow_policy')
    rental_workflow_requires_return_signature = fields.Boolean(
        string='Requires Return Signature',
        compute='_compute_rental_workflow_policy')
    rental_workflow_return_signature_due = fields.Boolean(
        string='Return Signature Due',
        compute='_compute_rental_workflow_return_signature_due')
    rental_show_dispatch_button = fields.Boolean(
        string='Show Dispatch Button', compute='_compute_rental_workflow_buttons')
    rental_show_install_button = fields.Boolean(
        string='Show Install Button', compute='_compute_rental_workflow_buttons')
    rental_show_start_rental_button = fields.Boolean(
        string='Show Start Rental Button',
        compute='_compute_rental_workflow_buttons')
    rental_show_start_inspection_button = fields.Boolean(
        string='Show Start Inspection Button',
        compute='_compute_rental_workflow_buttons')
    rental_show_close_button = fields.Boolean(
        string='Show Close Button', compute='_compute_rental_workflow_buttons')

    def _rental_workflow_assets(self):
        self.ensure_one()
        assets = self.env['gr.generator.asset']
        if self.asset_id:
            assets |= self.asset_id
        if 'item_line_ids' in self._fields:
            assets |= self.item_line_ids.mapped('equipment_asset_id')
        return assets

    def _has_legacy_item_lines(self):
        self.ensure_one()
        return bool(
            'item_line_ids' in self._fields
            and self.item_line_ids.filtered('item_unit_id'))

    @api.depends(
        'asset_id',
        'asset_id.rental_requires_dispatch',
        'asset_id.rental_requires_installation',
        'asset_id.rental_requires_meter_readings',
        'asset_id.rental_requires_delivery_inspection',
        'asset_id.rental_requires_return_inspection',
        'asset_id.rental_requires_delivery_signature',
        'asset_id.rental_requires_return_signature',
        'state',
    )
    def _compute_rental_workflow_policy(self):
        for order in self:
            assets = order._rental_workflow_assets()
            has_legacy_items = order._has_legacy_item_lines()

            def any_asset(flag):
                return any(assets.mapped(flag)) if assets else False

            requires_installation = any_asset('rental_requires_installation')
            requires_dispatch = (
                any_asset('rental_requires_dispatch')
                or requires_installation
                or has_legacy_items)
            order.rental_workflow_requires_dispatch = requires_dispatch
            order.rental_workflow_requires_installation = requires_installation
            order.rental_workflow_requires_meter_readings = any_asset(
                'rental_requires_meter_readings')
            order.rental_workflow_requires_delivery_inspection = any_asset(
                'rental_requires_delivery_inspection')
            order.rental_workflow_requires_return_inspection = any_asset(
                'rental_requires_return_inspection')
            order.rental_workflow_requires_delivery_signature = any_asset(
                'rental_requires_delivery_signature')
            order.rental_workflow_requires_return_signature = any_asset(
                'rental_requires_return_signature')

    @api.depends('state', 'rental_workflow_requires_return_signature')
    def _compute_rental_workflow_return_signature_due(self):
        for order in self:
            order.rental_workflow_return_signature_due = (
                order.rental_workflow_requires_return_signature
                and order.state in ('on_rent', 'off_hire_requested'))

    def _check_return_signature_required(self):
        missing = self.filtered(
            lambda order: order.rental_workflow_return_signature_due
            and not order.customer_return_signature)
        if missing:
            raise UserError(_(
                "Capture the customer's return signature before returning "
                "rental order %s.") % ', '.join(missing.mapped('name')))

    @api.depends(
        'state',
        'rental_workflow_requires_dispatch',
        'rental_workflow_requires_installation',
        'rental_workflow_requires_meter_readings',
        'rental_workflow_requires_delivery_inspection',
        'rental_workflow_requires_return_inspection',
        'rental_workflow_requires_delivery_signature',
        'rental_workflow_requires_return_signature',
    )
    def _compute_rental_workflow_buttons(self):
        for order in self:
            order.rental_show_dispatch_button = (
                order.state == 'reserved'
                and order.rental_workflow_requires_dispatch)
            order.rental_show_install_button = (
                order.state == 'dispatched'
                and order.rental_workflow_requires_installation)
            order.rental_show_start_rental_button = (
                order.state == 'installed'
                or (
                    order.state == 'dispatched'
                    and not order.rental_workflow_requires_installation)
                or (
                    order.state == 'reserved'
                    and not order.rental_workflow_requires_dispatch))
            order.rental_show_start_inspection_button = (
                order.state == 'returned'
                and order.rental_workflow_requires_return_inspection)
            order.rental_show_close_button = (
                order.state == 'inspection'
                or (
                    order.state == 'returned'
                    and not order.rental_workflow_requires_return_inspection))

    @api.constrains('asset_id')
    def _check_asset_is_rentable(self):
        for order in self:
            if order.asset_id and not order.asset_id.is_rentable:
                raise ValidationError(_(
                    "Equipment %s is Customer-owned and cannot be put on a "
                    "rental order. It is serviced only, not rented.")
                    % order.asset_id.display_name)
            if order.asset_id and not order.asset_id.rental_standalone_ok:
                raise ValidationError(_(
                    "Equipment %s cannot be rented as the main standalone "
                    "asset. Add it only as an accessory or change its rental "
                    "workflow settings.")
                    % order.asset_id.display_name)

    def _check_rental_asset_usage_policy(self):
        for order in self:
            if order.asset_id and not order.asset_id.rental_standalone_ok:
                raise ValidationError(_(
                    "Equipment %s cannot be rented as the main standalone "
                    "asset.") % order.asset_id.display_name)
            if 'item_line_ids' not in order._fields:
                continue
            for line in order.item_line_ids.filtered('equipment_asset_id'):
                asset = line.equipment_asset_id
                if order.asset_id:
                    if not asset.rental_accessory_ok and not asset.is_generator_type:
                        raise ValidationError(_(
                            "Equipment %s cannot be added as an accessory "
                            "with another asset.") % asset.display_name)
                elif not asset.rental_standalone_ok:
                    raise ValidationError(_(
                        "Equipment %s cannot be rented standalone.")
                        % asset.display_name)

    def _equipment_current_vals(self, clear=False):
        self.ensure_one()
        if clear:
            return {
                'current_customer_id': False,
                'current_site_ref': False,
                'current_contract_ref': False,
                'current_rental_order_ref': False,
                'current_rental_order_id': False,
                'current_contract_id': False,
                'current_site_id': False,
                'expected_return_datetime': False,
                'dispatch_datetime': False,
            }
        return {
            'current_customer_id': self.partner_id.id,
            'current_site_ref': self.site_id.display_name if self.site_id else False,
            'current_contract_ref': self.contract_id.name if self.contract_id else False,
            'current_rental_order_ref': self.name,
            'current_rental_order_id': self.id,
            'current_contract_id': self.contract_id.id,
            'current_site_id': self.site_id.id,
            'expected_return_datetime': self.planned_return_datetime,
        }

    def _sync_equipment_current(self, clear=False, extra_vals=None, current_only=False):
        orders = self.filtered('asset_id')
        if current_only:
            orders = orders.filtered(
                lambda order: order._availability_should_touch_current_status())
        for order in orders:
            vals = order._equipment_current_vals(clear=clear)
            if extra_vals:
                vals.update(extra_vals)
            order.asset_id.with_context(
                gr_meter_correction=True,
                gr_skip_history_asset_write=True,
            ).write(vals)

    def _write_primary_asset_on_rent(self):
        for order in self.filtered('asset_id'):
            vals = order._equipment_current_vals()
            vals['status'] = 'on_rent'
            if order.rental_workflow_requires_meter_readings:
                vals['current_hour_meter'] = order.start_meter_reading
            order.asset_id.with_context(
                gr_meter_correction=True,
                gr_skip_history_asset_write=True,
            ).write(vals)

    def _write_primary_asset_returned(self):
        for order in self.filtered('asset_id'):
            vals = dict(order._equipment_current_vals(clear=True),
                        status='returned_pending_inspection')
            if order.rental_workflow_requires_meter_readings:
                vals['current_hour_meter'] = order.end_meter_reading
            order.asset_id.with_context(
                gr_meter_correction=True,
                gr_skip_history_asset_write=True,
            ).write(vals)

    def _close_primary_asset_without_return_inspection(self):
        for order in self.filtered('asset_id'):
            order.state = 'closed'
            if not order.asset_id.maintenance_overdue:
                order.asset_id.with_context(
                    gr_meter_correction=True,
                    gr_skip_history_asset_write=True,
                ).write(dict(order._equipment_current_vals(clear=True),
                             status='available'))

    def _check_asset_not_double_booked(self):
        return super()._check_asset_not_double_booked()

    def action_confirm(self):
        self._check_rental_asset_usage_policy()
        return super().action_confirm()

    def action_reserve(self):
        self._check_rental_asset_usage_policy()
        res = super().action_reserve()
        self._sync_equipment_current(current_only=True)
        return res

    def action_dispatch(self):
        blocked = self.filtered(
            lambda order: order.state == 'reserved'
            and not order.rental_workflow_requires_dispatch)
        if blocked:
            raise UserError(_(
                "Order %s does not require dispatch. Start the rental directly.")
                % ', '.join(blocked.mapped('name')))
        res = super().action_dispatch()
        self._sync_equipment_current(extra_vals={
            'dispatch_datetime': fields.Datetime.now(),
        })
        return res

    def action_install(self):
        compatibility = self.filtered(
            lambda order: order.asset_id
            and order.state == 'dispatched'
            and not order.rental_workflow_requires_installation)
        for order in compatibility:
            order.state = 'installed'
            order.actual_install_datetime = fields.Datetime.now()
            order._write_primary_asset_on_rent()
        todo = self - compatibility
        res = super(GrRentalOrderEquipment, todo).action_install() if todo else True
        todo._sync_equipment_current()
        return res

    def action_start_rental(self):
        direct = self.filtered(lambda order:
            order.asset_id and (
                (
                    order.state == 'reserved'
                    and not order.rental_workflow_requires_dispatch)
                or (
                    order.state == 'dispatched'
                    and not order.rental_workflow_requires_installation)))
        for order in direct:
            order.state = 'on_rent'
            order._write_primary_asset_on_rent()
        todo = self - direct
        res = super(GrRentalOrderEquipment, todo).action_start_rental() if todo else True
        todo._sync_equipment_current()
        return res

    def action_request_off_hire(self):
        res = super().action_request_off_hire()
        self._sync_equipment_current()
        return res

    def action_return(self):
        self._check_return_signature_required()
        no_meter = self.filtered(
            lambda order: order.asset_id
            and not order.rental_workflow_requires_meter_readings)
        for order in no_meter:
            if order.state not in ('on_rent', 'off_hire_requested'):
                raise UserError(_("Only on-rent or off-hire orders can be returned."))
            order.state = 'returned'
            order.actual_return_datetime = fields.Datetime.now()
            order._write_primary_asset_returned()
        todo = self - no_meter
        res = super(GrRentalOrderEquipment, todo).action_return() if todo else True
        todo._write_primary_asset_returned()
        return res

    def action_close(self):
        direct = self.filtered(
            lambda order: order.state == 'returned'
            and not order.rental_workflow_requires_return_inspection)
        direct._close_primary_asset_without_return_inspection()
        todo = self - direct
        res = super(GrRentalOrderEquipment, todo).action_close() if todo else True
        todo._sync_equipment_current(clear=True)
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._sync_equipment_current(clear=True)
        return res
