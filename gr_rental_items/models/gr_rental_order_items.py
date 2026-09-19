# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrRentalOrderItems(models.Model):
    """Rental orders can now carry item lines (cable, tank, panel...) alongside
    a generator, or with NO generator at all (standalone item rental).

    The base order's lifecycle assumes a generator exists (reserve/dispatch/
    install dereference asset_id). For a standalone item rental we take over
    those steps and drive the item units instead."""
    _inherit = 'gr.rental.order'

    item_line_ids = fields.One2many(
        'gr.rental.order.line', 'order_id',
        string='Rented Serials')
    # Kept on separate compute methods on purpose: a stored and a non-stored
    # field must not share one, or reading the non-stored count would recompute
    # and write the stored total (Odoo 19 warns about this).
    item_line_count = fields.Integer(
        string='Rental Lines', compute='_compute_item_line_count')
    items_total = fields.Monetary(
        string='Rental Lines Total', currency_field='currency_id',
        compute='_compute_items_total', store=True,
        help="Sum of the item lines (free lines contribute zero).")
    has_generator = fields.Boolean(
        string='Has Generator Serial',
        compute='_compute_has_generator', store=True)
    generator_serial_count = fields.Integer(
        string='Generator Serials',
        compute='_compute_has_generator', store=True)
    is_items_only = fields.Boolean(
        string='Accessories-only Rental',
        compute='_compute_has_generator', store=True,
        help="True when this order rents accessories or legacy items with no "
             "generator serial.")

    def _is_generator_asset(self, asset):
        return bool(
            asset
            and (
                'is_generator_type' not in asset._fields
                or asset.is_generator_type))

    def _primary_asset_line(self):
        self.ensure_one()
        lines = self.item_line_ids.filtered('equipment_asset_id')
        if not lines:
            return self.env['gr.rental.order.line']
        if self.asset_id:
            matching = lines.filtered(
                lambda line: line.equipment_asset_id == self.asset_id)
            return matching[:1]
        generator_lines = lines.filtered(
            lambda line: self._is_generator_asset(line.equipment_asset_id))
        return (generator_lines or lines)[:1]

    def _sync_primary_asset_from_lines(self):
        if self.env.context.get('gr_skip_primary_asset_sync'):
            return
        Line = self.env['gr.rental.order.line']
        editable_states = ('draft', 'confirmed')
        for order in self:
            primary_line = order._primary_asset_line()
            if order.asset_id and not primary_line:
                primary_line = Line.with_context(
                    gr_skip_primary_asset_sync=True).create({
                        'order_id': order.id,
                        'equipment_asset_id': order.asset_id.id,
                        'is_primary_asset_line': True,
                    })
            desired_asset = primary_line.equipment_asset_id if primary_line else False
            if desired_asset and order.asset_id != desired_asset \
                    and order.state in editable_states:
                order.with_context(gr_skip_primary_asset_sync=True).write({
                    'asset_id': desired_asset.id,
                })
            elif not desired_asset and order.asset_id \
                    and order.state in editable_states:
                order.with_context(gr_skip_primary_asset_sync=True).write({
                    'asset_id': False,
                })

            lines = order.item_line_ids.filtered('equipment_asset_id')
            if not lines:
                continue
            primary_line = order._primary_asset_line()
            lines.with_context(gr_skip_primary_asset_sync=True).write({
                'is_primary_asset_line': False,
            })
            if primary_line:
                primary_line.with_context(gr_skip_primary_asset_sync=True).write({
                    'is_primary_asset_line': True,
                })

    @api.depends(
        'asset_id',
        'asset_id.is_generator_type',
        'item_line_ids',
        'item_line_ids.equipment_asset_id',
        'item_line_ids.equipment_asset_id.is_generator_type',
        'item_line_ids.item_unit_id',
    )
    def _compute_has_generator(self):
        for o in self:
            generator_assets = self.env['gr.generator.asset']
            if o._is_generator_asset(o.asset_id):
                generator_assets |= o.asset_id
            generator_assets |= o.item_line_ids.mapped(
                'equipment_asset_id').filtered(o._is_generator_asset)
            o.generator_serial_count = len(generator_assets)
            o.has_generator = bool(o.generator_serial_count)
            o.is_items_only = bool(not o.has_generator and o.item_line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._sync_primary_asset_from_lines()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if 'asset_id' in vals:
            self._sync_primary_asset_from_lines()
        return res

    @api.depends('item_line_ids')
    def _compute_item_line_count(self):
        for o in self:
            o.item_line_count = len(o.item_line_ids)

    @api.depends('item_line_ids.line_total')
    def _compute_items_total(self):
        for o in self:
            o.items_total = sum(o.item_line_ids.mapped('line_total'))

    @api.depends(
        'asset_id',
        'asset_id.rental_requires_dispatch',
        'asset_id.rental_requires_installation',
        'asset_id.rental_requires_meter_readings',
        'asset_id.rental_requires_delivery_inspection',
        'asset_id.rental_requires_return_inspection',
        'asset_id.rental_requires_delivery_signature',
        'asset_id.rental_requires_return_signature',
        'item_line_ids.equipment_asset_id',
        'item_line_ids.equipment_asset_id.rental_requires_dispatch',
        'item_line_ids.equipment_asset_id.rental_requires_installation',
        'item_line_ids.equipment_asset_id.rental_requires_meter_readings',
        'item_line_ids.equipment_asset_id.rental_requires_delivery_inspection',
        'item_line_ids.equipment_asset_id.rental_requires_return_inspection',
        'item_line_ids.equipment_asset_id.rental_requires_delivery_signature',
        'item_line_ids.equipment_asset_id.rental_requires_return_signature',
        'item_line_ids.item_unit_id',
        'state',
    )
    def _compute_rental_workflow_policy(self):
        return super()._compute_rental_workflow_policy()

    # ------------------------------------------------------------------
    # Guards run in the ACTIONS (state transitions), NOT @api.constrains on
    # fields: a constraint watching asset_id/item_line_ids does not re-fire
    # when only `state` is written, so it would never catch these cases.
    # ------------------------------------------------------------------
    def _check_rents_something(self):
        for o in self:
            if not o.asset_id and not o.item_line_ids:
                raise UserError(_(
                    "Order %s has no rented serials. Add every generator or "
                    "accessory serial in the Rented Serials tab.")
                    % o.name)

    def _check_items_not_double_booked(self, lock=False):
        return self._check_order_availability(lock=lock, exception='validation')

    def _reserve_item_units(self):
        return self._check_order_availability(lock=False, exception='user')

    def _line_asset_current_vals(self, order, clear=False):
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
            'current_customer_id': order.partner_id.id,
            'current_site_ref': order.site_id.display_name if order.site_id else False,
            'current_contract_ref': order.contract_id.name if order.contract_id else False,
            'current_rental_order_ref': order.name,
            'current_rental_order_id': order.id,
            'current_contract_id': order.contract_id.id,
            'current_site_id': order.site_id.id,
            'expected_return_datetime': order.planned_return_datetime,
        }

    def _set_equipment_line_assets_status(self, status, clear=False, current_only=False):
        orders = self
        if current_only:
            orders = orders.filtered(
                lambda order: order._availability_should_touch_current_status())
        for order in orders:
            assets = order.item_line_ids.mapped('equipment_asset_id')
            for asset in assets.filtered(
                    lambda a: a.status not in ('retired', 'under_maintenance',
                                               'maintenance_due')):
                vals = order._line_asset_current_vals(order, clear=clear)
                vals['status'] = status
                if status == 'in_transit':
                    vals['dispatch_datetime'] = fields.Datetime.now()
                asset.with_context(
                    gr_meter_correction=True,
                    gr_skip_history_asset_write=True,
                ).write(vals)

    def _set_item_units_status(self, status, current_only=False):
        orders = self
        if current_only:
            orders = orders.filtered(
                lambda order: order._availability_should_touch_current_status())
        units = orders.mapped('item_line_ids.item_unit_id')
        units.filtered(
            lambda u: u.status not in ('retired', 'maintenance')
        ).write({'status': status})

    def _items_only(self):
        return self.filtered(lambda o: not o.asset_id and o.item_line_ids)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def action_confirm(self):
        self._check_rents_something()
        return super().action_confirm()

    def action_reserve(self):
        io = self._items_only()
        wg = self - io
        for o in io:
            if o.state != 'confirmed':
                raise UserError(_("Only confirmed orders can be reserved."))
            o._check_items_not_double_booked(lock=True)
            o._set_item_units_status('on_rent', current_only=True)
            o._set_equipment_line_assets_status('reserved', current_only=True)
            o.state = 'reserved'
        if wg:
            wg._check_items_not_double_booked(lock=True)
            res = super(GrRentalOrderItems, wg).action_reserve()
            wg._set_item_units_status('on_rent', current_only=True)
            wg._set_equipment_line_assets_status('reserved', current_only=True)
            return res
        return True

    def action_dispatch(self):
        io = self._items_only()
        wg = self - io
        for o in io:
            if o.state != 'reserved':
                raise UserError(_("Only reserved orders can be dispatched."))
            if ('rental_workflow_requires_dispatch' in o._fields
                    and not o.rental_workflow_requires_dispatch):
                raise UserError(_(
                    "Order %s does not require dispatch. Start the rental directly.")
                    % o.name)
            if ('rental_workflow_requires_delivery_inspection' in o._fields
                    and o.rental_workflow_requires_delivery_inspection
                    and 'delivery_inspection_passed' in o._fields
                    and not o.delivery_inspection_passed):
                raise UserError(_(
                    "Cannot dispatch %s: a passed DELIVERY inspection is "
                    "required first.") % o.name)
            o.state = 'dispatched'
            o.actual_dispatch_datetime = fields.Datetime.now()
            o._set_equipment_line_assets_status('in_transit')
        if wg:
            res = super(GrRentalOrderItems, wg).action_dispatch()
            wg._set_item_units_status('on_rent')
            wg._set_equipment_line_assets_status('in_transit')
            return res
        return True

    def action_install(self):
        io = self._items_only()
        wg = self - io
        for o in io:
            if o.state != 'dispatched':
                raise UserError(_("Only dispatched orders can be installed."))
            # Backward compatibility: older item-only flows may still call
            # Install even when the equipment policy no longer requires it.
            o.state = 'installed'
            o.actual_install_datetime = fields.Datetime.now()
            o._set_equipment_line_assets_status('on_rent')
        if wg:
            res = super(GrRentalOrderItems, wg).action_install()
            wg._set_equipment_line_assets_status('on_rent')
            return res
        return True

    def action_start_rental(self):
        io = self._items_only()
        wg = self - io
        for o in io:
            can_start = (
                o.state == 'installed'
                or (
                    'rental_workflow_requires_installation' in o._fields
                    and o.state == 'dispatched'
                    and not o.rental_workflow_requires_installation)
                or (
                    'rental_workflow_requires_dispatch' in o._fields
                    and o.state == 'reserved'
                    and not o.rental_workflow_requires_dispatch))
            if not can_start:
                raise UserError(_("Only installed orders can start the rental."))
            o.state = 'on_rent'
            o._set_equipment_line_assets_status('on_rent')
        if wg:
            res = super(GrRentalOrderItems, wg).action_start_rental()
            wg._set_equipment_line_assets_status('on_rent')
            return res
        return True

    def action_return(self):
        io = self._items_only()
        wg = self - io
        io._check_return_signature_required()
        for o in io:
            o.state = 'returned'
            o.actual_return_datetime = fields.Datetime.now()
            o._set_equipment_line_assets_status('returned_pending_inspection')
            if ('rental_workflow_requires_return_inspection' in o._fields
                    and o.rental_workflow_requires_return_inspection
                    and 'gr.rental.inspection' in self.env):
                existing = o.inspection_ids.filtered(lambda i: i.mode == 'return')
                if not existing:
                    insp = self.env['gr.rental.inspection'].create({
                        'rental_order_id': o.id,
                        'mode': 'return',
                    })
                    insp._populate_default_checklist()
        if wg:
            res = super(GrRentalOrderItems, wg).action_return()
            wg._set_equipment_line_assets_status('returned_pending_inspection')
            return res
        return True

    def action_start_inspection(self):
        io = self._items_only()
        wg = self - io
        for o in io:
            if ('rental_workflow_requires_return_inspection' in o._fields
                    and not o.rental_workflow_requires_return_inspection):
                raise UserError(_(
                    "Order %s does not require return inspection. Close it directly.")
                    % o.name)
            o.state = 'inspection'
            o._set_equipment_line_assets_status('returned_pending_inspection')
        if wg:
            return super(GrRentalOrderItems, wg).action_start_inspection()
        return True

    def action_close(self):
        io = self._items_only()
        wg = self - io
        for o in io:
            if o.state not in ('inspection', 'returned'):
                raise UserError(_("Only returned orders can be closed."))
            if (o.state == 'returned'
                    and 'rental_workflow_requires_return_inspection' in o._fields
                    and o.rental_workflow_requires_return_inspection):
                if 'return_inspection_passed' in o._fields \
                        and o.return_inspection_passed:
                    o.state = 'closed'
                    continue
                raise UserError(_(
                    "Cannot close %s: a passed RETURN inspection is required first.")
                    % o.name)
            o.state = 'closed'
        res = super(GrRentalOrderItems, wg).action_close() if wg else True
        self._set_item_units_status('available')
        self._set_equipment_line_assets_status('available', clear=True)
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._set_item_units_status('available')
        self._set_equipment_line_assets_status('available', clear=True)
        return res
