# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StrxCabinShippingOrder(models.Model):
    """Shipment for one movement: broker, driver, vehicle, route, cost and dates,
    linked to the rental order and the exact serials carried."""
    _name = 'strx.cabin.shipping.order'
    _description = 'Cabin Shipping Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Shipment', required=True, copy=False, readonly=True,
                       index=True, default=lambda self: _('New'))

    broker_id = fields.Many2one('strx.cabin.broker', string='Broker', required=True,
                                tracking=True)
    broker_waybill_ref = fields.Char(
        string='Shipment Tracking Number',
        tracking=True,
        help="Tracking number provided by the carrier for this shipment.")
    is_internal = fields.Boolean(related='broker_id.is_internal', store=True,
                                 string='Company Transport')

    order_id = fields.Many2one('sale.order', string='Rental Order', tracking=True,
                               index=True)
    allocation_ids = fields.Many2many(
        'strx.cabin.allocation',
        'strx_cabin_allocation_shipping_order_rel',
        'shipping_order_id',
        'allocation_id',
        string='Cabin Allocations',
        compute='_compute_allocation_ids',
        store=True,
        copy=False,
        readonly=True,
        help="Allocations whose exact cabin serials are carried by this shipment.")
    partner_id = fields.Many2one('res.partner', related='order_id.partner_id',
                                 store=True, readonly=True)
    movement_type = fields.Selection(
        selection=[
            ('delivery', 'Delivery'),
            ('return', 'Return'),
            ('site_transfer', 'Site Transfer'),
        ],
        string='Movement', default='delivery', required=True, tracking=True,
        help="Delivery sends the cabin to the customer. Return receives it back "
             "from the customer to the yard. Site Transfer moves an on-rent cabin "
             "directly from one customer site to another without returning it to "
             "the yard.")
    lot_ids = fields.Many2many('stock.lot', string='Serials Carried',
                               help="The exact physical units on this shipment.")
    allowed_order_ids = fields.Many2many(
        'sale.order', compute='_compute_allowed_orders_and_lots',
        string='Allowed Rental Orders')
    eligible_lot_ids = fields.Many2many(
        'stock.lot', compute='_compute_allowed_orders_and_lots',
        string='Eligible Serials')

    # Driver / vehicle
    driver_name = fields.Char(string='Driver', tracking=True)
    driver_id_number = fields.Char(string='Driver ID')
    driver_phone = fields.Char(string='Driver Phone')
    vehicle_model = fields.Char(string='Vehicle')
    vehicle_plate = fields.Char(string='Plate', tracking=True)

    # Route
    route_origin = fields.Char(string='Origin')
    route_destination = fields.Char(string='Destination')
    route_note = fields.Text(
        string='Route Notes',
        help="Optional pickup/drop-off instructions, checkpoints, or site access "
             "notes for this shipment.")

    # Cost (rolls up to the rental order for margin visibility)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    agreed_cost = fields.Monetary(
        string='Agreed Cost',
        currency_field='currency_id',
        default=0.0,
        tracking=True)
    broker_payment_ids = fields.Many2many(
        'strx.cabin.broker.payment',
        'strx_cabin_broker_payment_shipping_order_rel',
        'shipping_order_id', 'payment_id',
        string='Broker Payment Orders',
        readonly=True)
    broker_payment_count = fields.Integer(
        string='Payment Orders', compute='_compute_broker_payment')
    broker_payment_state = fields.Selection(
        selection=[
            ('none', 'Not Billed'),
            ('draft', 'Draft Payment'),
            ('issued', 'Payment Issued'),
            ('approved', 'Payment Approved'),
            ('paid', 'Paid'),
        ],
        string='Payment Status', compute='_compute_broker_payment',
        search='_search_broker_payment_state')

    # Dates
    scheduled_date = fields.Datetime(string='Planned Date')
    loaded_date = fields.Datetime(string='Loaded On', readonly=True, copy=False)
    shipped_date = fields.Datetime(string='Shipped On', readonly=True, copy=False)
    delivered_date = fields.Datetime(string='Delivered On', readonly=True, copy=False)

    # Customer receipt proof
    customer_receipt_signature = fields.Image(
        string='Customer Signature / Stamp',
        copy=False,
        attachment=True,
        help="Customer signature or company stamp on the delivery receipt.")
    customer_receipt_attachment_ids = fields.Many2many(
        'ir.attachment',
        'strx_shipping_order_receipt_attachment_rel',
        'shipping_order_id',
        'attachment_id',
        string='Receipt Attachments',
        copy=False,
        help="Attach the signed/stamped delivery receipt or any supporting proof.")
    customer_receipt_exception = fields.Boolean(
        string='Customer Did Not Sign',
        copy=False,
        tracking=True,
        help="Use only when the customer did not sign or stamp the receipt.")
    customer_receipt_exception_reason = fields.Text(
        string='Exception Reason',
        copy=False,
        tracking=True)

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('issued', 'Issued'),
            ('loaded', 'Loaded'),
            ('shipped', 'Shipped'),
            ('delivered', 'Delivered'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, copy=False, tracking=True)

    note = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('order_id', 'lot_ids')
    def _compute_allocation_ids(self):
        """Persist the precise allocation ↔ shipment link for auditability.

        Matching both the rental order and serials prevents a reused cabin serial
        from linking an unrelated rental.  Because the result is stored, completed
        delivery/return history remains attached even after an allocation's current
        serial selection changes later.
        """
        Allocation = self.env['strx.cabin.allocation']
        for shipment in self:
            if not shipment.order_id or not shipment.lot_ids:
                shipment.allocation_ids = False
                continue
            shipment.allocation_ids = Allocation.search([
                ('order_id', '=', shipment.order_id.id),
                ('lot_ids', 'in', shipment.lot_ids.ids),
            ])

    def init(self):
        """Backfill allocation links for shipments created before this relation."""
        self.env.cr.execute("""
            INSERT INTO strx_cabin_allocation_shipping_order_rel
                        (shipping_order_id, allocation_id)
                 SELECT DISTINCT shipment.id, allocation.id
                   FROM strx_cabin_shipping_order shipment
                   JOIN stock_lot_strx_cabin_shipping_order_rel shipment_lot
                     ON shipment_lot.strx_cabin_shipping_order_id = shipment.id
                   JOIN strx_cabin_allocation_stock_lot_rel allocation_lot
                     ON allocation_lot.lot_id = shipment_lot.stock_lot_id
                   JOIN strx_cabin_allocation allocation
                     ON allocation.id = allocation_lot.allocation_id
                    AND allocation.order_id = shipment.order_id
            ON CONFLICT DO NOTHING
        """)

    @api.depends('broker_payment_ids.state')
    def _compute_broker_payment(self):
        ranking = {
            'none': 0,
            'draft': 1,
            'issued': 2,
            'approved': 3,
            'paid': 4,
        }
        for waybill in self:
            payments = waybill.broker_payment_ids.filtered(
                lambda p: p.state != 'cancel')
            waybill.broker_payment_count = len(payments)
            state = 'none'
            for payment in payments:
                if ranking[payment.state] > ranking[state]:
                    state = payment.state
            waybill.broker_payment_state = state

    def _search_broker_payment_state(self, operator, value):
        if operator not in ('=', '!=', 'in', 'not in'):
            raise UserError(_("Unsupported payment-status search operator."))
        values = value if isinstance(value, (list, tuple)) else [value]
        if 'none' in values:
            paid_ids = self.env['strx.cabin.broker.payment'].search([
                ('state', '!=', 'cancel'),
            ]).mapped('shipping_order_ids').ids
            domain = [('id', 'not in', paid_ids)]
        else:
            payment_ids = self.env['strx.cabin.broker.payment'].search([
                ('state', operator if operator in ('=', 'in') else '=', value),
            ])
            domain = [('id', 'in', payment_ids.mapped('shipping_order_ids').ids)]
        if operator in ('!=', 'not in'):
            domain = ['!'] + domain
        return domain

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'strx.cabin.shipping.order') or _('New')
            self._strx_prepare_lots(vals)
        waybills = super().create(vals_list)
        if not self.env.context.get('strx_migration'):
            for waybill in waybills:
                waybill._strx_validate_configuration()
        return waybills

    def write(self, vals):
        protected = {'order_id', 'movement_type', 'lot_ids'}
        if protected & set(vals) and not self.env.context.get('strx_shipping_autofill_lots'):
            locked = self.filtered(lambda w: w.state not in ('draft', 'cancel'))
            if locked:
                raise UserError(_(
                    "You can only change the rental, movement, or carried serials while "
                    "the shipment is still Draft."))
        res = super().write(vals)
        if self.env.context.get('strx_shipping_autofill_lots'):
            return res
        if {'order_id', 'movement_type'} & set(vals) and 'lot_ids' not in vals:
            for waybill in self:
                waybill._strx_autofill_lots()
        if protected & set(vals) and not self.env.context.get('strx_migration'):
            for waybill in self:
                waybill._strx_validate_configuration()
        return res

    @api.onchange('broker_id')
    def _onchange_broker_id(self):
        for waybill in self:
            broker = waybill.broker_id
            if not broker:
                continue
            if not waybill.agreed_cost and broker.default_rate:
                waybill.agreed_cost = broker.default_rate
                waybill.currency_id = broker.currency_id or waybill.currency_id

    @api.depends('order_id', 'movement_type', 'state')
    def _compute_allowed_orders_and_lots(self):
        Allocation = self.env['strx.cabin.allocation']
        for waybill in self:
            if waybill.movement_type == 'return':
                order_allocs = Allocation.search([
                    ('lot_ids', '!=', False),
                    ('state', '=', 'on_rent'),
                ]).filtered(lambda alloc: all(
                    not lot.strx_hidden_from_selection
                    and lot.strx_readiness_state in ('on_rent', 'return_due')
                    for lot in alloc.lot_ids))
            elif waybill.movement_type == 'site_transfer':
                order_allocs = Allocation.search([
                    ('lot_ids', '!=', False),
                    ('state', '=', 'on_rent'),
                ]).filtered(lambda alloc: all(
                    not lot.strx_hidden_from_selection
                    and lot.strx_readiness_state == 'on_rent'
                    for lot in alloc.lot_ids))
            else:
                order_allocs = Allocation.search([
                    ('lot_ids', '!=', False),
                    ('state', '=', 'allocated'),
                ]).filtered(lambda alloc: all(
                    not lot.strx_hidden_from_selection
                    and lot.strx_readiness_state == 'allocated'
                    for lot in alloc.lot_ids))
            waybill.allowed_order_ids = order_allocs.mapped('order_id')
            waybill.eligible_lot_ids = waybill._strx_candidate_allocations(
                'config').mapped('lot_ids') if waybill.order_id else False

    @api.onchange('order_id', 'movement_type')
    def _onchange_order_id(self):
        for waybill in self:
            waybill.lot_ids = waybill._strx_candidate_allocations(
                'config').mapped('lot_ids') if waybill.order_id else False

    # --------------------------------------- allocation/readiness automation
    @api.model
    def _strx_prepare_lots(self, vals):
        if vals.get('lot_ids') or not vals.get('order_id'):
            return
        movement = vals.get('movement_type') or 'delivery'
        order = self.env['sale.order'].browse(vals['order_id'])
        allocations = self._strx_candidate_allocations_for(order, movement, 'config')
        if allocations:
            vals['lot_ids'] = [(6, 0, allocations.mapped('lot_ids').ids)]

    def _strx_autofill_lots(self):
        self.ensure_one()
        self.with_context(strx_shipping_autofill_lots=True).write({
            'lot_ids': [(6, 0, self._strx_candidate_allocations('config').mapped('lot_ids').ids)]
        })

    @api.model
    def _strx_candidate_allocations_for(self, order, movement_type, stage):
        if not order:
            return self.env['strx.cabin.allocation']
        domain = [
            ('order_id', '=', order.id),
            ('lot_ids', '!=', False),
        ]
        if movement_type == 'return':
            domain.append(('state', '=', 'on_rent'))
            if stage == 'deliver':
                readiness_states = ('return_due',)
            else:
                readiness_states = ('on_rent', 'return_due')
        elif movement_type == 'site_transfer':
            domain.append(('state', '=', 'on_rent'))
            readiness_states = ('on_rent',)
        else:
            domain.append(('state', '=', 'dispatched' if stage == 'deliver'
                           else 'allocated'))
            readiness_states = (
                'dispatched' if stage == 'deliver' else 'allocated',)
        return self.env['strx.cabin.allocation'].search(domain).filtered(
            lambda alloc: all(
                not lot.strx_hidden_from_selection
                and lot.strx_readiness_state in readiness_states
                for lot in alloc.lot_ids))

    def _strx_candidate_allocations(self, stage):
        self.ensure_one()
        return self._strx_candidate_allocations_for(
            self.order_id, self.movement_type, stage)

    def _strx_validate_configuration(self):
        """Refuse a waybill whose rental has nothing at the right stage to carry.

        Skipped under the ``strx_migration`` context flag. Loading finished
        shipments from another database replays documents whose allocations are
        already past the stage this checks for, so the check would reject history
        that is, by definition, already valid. The flag is set only by the
        migration script; nothing in normal use sets it.
        """
        self.ensure_one()
        if not self.order_id:
            return
        allocations = self._strx_candidate_allocations('config')
        if not allocations:
            raise UserError(_(
                "Rental %(order)s is not ready for %(movement)s shipping.",
                order=self.order_id.display_name,
                movement=dict(self._fields['movement_type']._description_selection(
                    self.env)).get(self.movement_type, self.movement_type)))
        self._strx_validate_selected_lots('config', require_lots=False)

    def _strx_validate_selected_lots(self, stage, require_lots=True):
        self.ensure_one()
        if not self.order_id:
            raise UserError(_("Select a rental order before proceeding."))
        if require_lots and not self.lot_ids:
            raise UserError(_("Add at least one carried serial before proceeding."))

        candidates = self._strx_candidate_allocations(stage)
        if require_lots and not candidates:
            raise UserError(_(
                "Rental %(order)s has no eligible allocations for this %(movement)s step.",
                order=self.order_id.display_name,
                movement=dict(self._fields['movement_type']._description_selection(
                    self.env)).get(self.movement_type, self.movement_type)))
        if not self.lot_ids:
            return candidates

        candidate_lots = candidates.mapped('lot_ids')
        invalid = self.lot_ids - candidate_lots
        if invalid:
            raise UserError(_(
                "Cannot update logistics status for shipment %(shipment)s.\n"
                "These serials are not eligible for rental %(order)s: %(serials)s",
                shipment=self.name,
                order=self.order_id.display_name,
                serials=", ".join(invalid.mapped('name'))))
        selected = candidates.filtered(lambda alloc: bool(alloc.lot_ids & self.lot_ids))
        partial = selected.filtered(lambda alloc: bool(alloc.lot_ids - self.lot_ids))
        if partial:
            raise UserError(_(
                "Shipment %(shipment)s must carry all serials from allocation "
                "%(allocation)s: %(serials)s",
                shipment=self.name,
                allocation=partial[0].name,
                serials=", ".join(partial[0].lot_ids.mapped('name'))))
        return selected

    def _strx_validate_waybill_details(self):
        """A real shipment may not leave Draft without complete bill data."""
        self.ensure_one()
        missing_by_section = []

        def add_section(title, items):
            if items:
                missing_by_section.append((title, items))

        broker = self.broker_id
        if not broker:
            add_section(
                _('Broker details'),
                [_('Shipping broker')],
            )
        else:
            broker_missing = []
            if not broker.company_registration:
                broker_missing.append(_('CR Number'))
            if not broker.contact_name:
                broker_missing.append(_('Broker contact'))
            if not broker.contact_phone:
                broker_missing.append(_('Broker phone'))
            add_section(_('Broker details'), broker_missing)

        required_fields = [
            ('driver_name', _('Driver name'), _('Driver & vehicle')),
            ('driver_id_number', _('Driver ID'), _('Driver & vehicle')),
            ('driver_phone', _('Driver phone'), _('Driver & vehicle')),
            ('vehicle_model', _('Vehicle'), _('Driver & vehicle')),
            ('vehicle_plate', _('Plate number'), _('Driver & vehicle')),
            ('route_origin', _('Origin'), _('Route & cost')),
            ('route_destination', _('Destination'), _('Route & cost')),
            ('scheduled_date', _('Planned date'), _('Route & cost')),
        ]
        grouped = {}
        for field_name, item_label, section in required_fields:
            if not self[field_name]:
                grouped.setdefault(section, []).append(item_label)
        if not self.agreed_cost or self.agreed_cost <= 0:
            section = _('Route & cost')
            grouped.setdefault(section, []).append(
                _('Agreed cost'))
        for section, items in grouped.items():
            missing_by_section.append((section, items))

        if missing_by_section:
            lines = [
                _("Shipment details are incomplete"),
                _("Complete the following details before issuing %s:")
                % self.display_name,
                "",
            ]
            for section, items in missing_by_section:
                lines.append(section)
                lines.extend("• %s" % item for item in items)
                lines.append("")
            lines.append(_('Tip: keep the shipment in Draft until the broker, driver, vehicle, route, and cost are confirmed.'))
            raise UserError("\n".join(lines).strip())

    def _strx_has_customer_receipt_signature(self):
        self.ensure_one()
        order = self.order_id
        return bool(
            self.customer_receipt_signature
            or (order and order.strx_customer_receipt_signature)
        )

    def _strx_has_customer_receipt_attachment(self):
        self.ensure_one()
        order = self.order_id
        return bool(
            self.customer_receipt_attachment_ids
            or (order and order.strx_customer_receipt_attachment_ids)
        )

    def _strx_has_customer_receipt_proof(self):
        """Complete proof always contains both a signature and an attachment."""
        self.ensure_one()
        return bool(
            self._strx_has_customer_receipt_signature()
            and self._strx_has_customer_receipt_attachment()
        )

    def _strx_has_customer_receipt_exception(self):
        self.ensure_one()
        order = self.order_id
        return bool(
            (
                self.customer_receipt_exception
                and (self.customer_receipt_exception_reason or '').strip()
            )
            or (
                order
                and order.strx_customer_receipt_exception
                and (order.strx_customer_receipt_exception_reason or '').strip()
            )
        )

    def _strx_validate_customer_receipt_before_delivery(self):
        """Customer-facing deliveries need receipt proof before final delivery.

        Returns are intentionally excluded because operational return shipments can
        be completed automatically from the allocation screen.
        """
        self.ensure_one()
        if self.movement_type not in ('delivery', 'site_transfer'):
            return
        has_signature = self._strx_has_customer_receipt_signature()
        has_attachment = self._strx_has_customer_receipt_attachment()
        has_exception = self._strx_has_customer_receipt_exception()
        if has_attachment and (has_signature or has_exception):
            return

        missing = []
        if not has_attachment:
            missing.append(_(
                "• At least one receipt attachment on the shipment or sales order."
            ))
        if not has_signature and not has_exception:
            missing.append(_(
                "• Customer signature/stamp, or a documented no-signature exception."
            ))
        raise UserError(_(
            "Shipment %(shipment)s cannot be delivered without complete customer receipt proof.\n\n"
            "Required:\n%(missing)s",
            shipment=self.display_name,
            missing="\n".join(missing),
        ))

    @api.constrains(
        'state', 'movement_type', 'order_id',
        'customer_receipt_signature', 'customer_receipt_attachment_ids',
        'customer_receipt_exception', 'customer_receipt_exception_reason',
    )
    def _check_customer_receipt_on_delivered_state(self):
        """Also protect direct RPC/import writes that set a shipment delivered."""
        for shipment in self.filtered(lambda record: record.state == 'delivered'):
            shipment._strx_validate_customer_receipt_before_delivery()

    def _strx_sync_delivery(self, event):
        self.ensure_one()
        allocations = self._strx_validate_selected_lots(event)
        if not allocations:
            return

        if self.movement_type == 'delivery':
            if event == 'ship':
                allocations.filtered(
                    lambda a: a.state in ('draft', 'allocated')).write({
                        'state': 'dispatched',
                    })
                for lot in allocations.mapped('lot_ids'):
                    lot._strx_set_readiness(
                        'dispatched',
                        reason=_("Shipped on shipment %(ref)s", ref=self.name))
            elif event == 'deliver':
                allocations.filtered(
                    lambda a: a.state in ('draft', 'allocated', 'dispatched')).write({
                        'state': 'on_rent',
                    })
                for lot in allocations.mapped('lot_ids'):
                    lot._strx_set_readiness(
                        'on_rent',
                        reason=_("Delivered on shipment %(ref)s", ref=self.name))
            return

        if self.movement_type == 'site_transfer':
            # A direct site-to-site transfer does not return the unit to the yard,
            # so the commercial allocation and the physical serial remain On Rent.
            # The shipment state + route fields are the movement record.
            if event == 'ship':
                self.message_post(body=_(
                    "Site transfer shipped on shipment %(ref)s", ref=self.name))
            elif event == 'deliver':
                self.message_post(body=_(
                    "Site transfer delivered on shipment %(ref)s", ref=self.name))
            return

        if event == 'ship':
            for lot in allocations.mapped('lot_ids'):
                lot._strx_set_readiness(
                    'return_due',
                    reason=_("Return shipped on shipment %(ref)s", ref=self.name))
        elif event == 'deliver':
            allocations.filtered(
                lambda a: a.state in ('draft', 'allocated', 'dispatched',
                                      'on_rent', 'returned')).write({
                    'state': 'returned',
                    'strx_actual_return_date': fields.Date.context_today(self),
                })
            for lot in allocations.mapped('lot_ids'):
                lot._strx_set_readiness(
                    'returned',
                    reason=_("Returned on shipment %(ref)s", ref=self.name))

    # ------------------------------------------------- status flow (Issued → …)
    def action_issue(self):
        for waybill in self:
            waybill._strx_validate_waybill_details()
            waybill._strx_validate_selected_lots('issue')
        self.write({'state': 'issued'})

    def action_load(self):
        for waybill in self:
            waybill._strx_validate_selected_lots('load')
        self.write({'state': 'loaded', 'loaded_date': fields.Datetime.now()})

    def action_ship(self):
        for waybill in self:
            waybill._strx_validate_selected_lots('ship')
        self.write({'state': 'shipped', 'shipped_date': fields.Datetime.now()})
        for waybill in self:
            waybill._strx_sync_delivery('ship')

    def action_deliver(self):
        for waybill in self:
            waybill._strx_validate_selected_lots('deliver')
            waybill._strx_validate_customer_receipt_before_delivery()
        self.write({'state': 'delivered', 'delivered_date': fields.Datetime.now()})
        for waybill in self:
            waybill._strx_sync_delivery('deliver')

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def action_view_broker_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Broker Payment Orders'),
            'res_model': 'strx.cabin.broker.payment',
            'view_mode': 'list,form',
            'domain': [('shipping_order_ids', 'in', self.id)],
            'context': {'default_broker_id': self.broker_id.id},
        }

    def action_create_broker_payment(self):
        self.ensure_one()
        if self.state != 'delivered':
            raise UserError(_("Only delivered shipments can be sent to broker payment."))
        if not self.agreed_cost or self.agreed_cost <= 0:
            raise UserError(_("Set the agreed cost before creating a shipment payment."))
        payment = self.env['strx.cabin.broker.payment'].create({
            'broker_id': self.broker_id.id,
            'currency_id': self.currency_id.id,
            'payment_batch': 'single',
            'shipping_order_ids': [(6, 0, self.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipment Payment'),
            'res_model': 'strx.cabin.broker.payment',
            'res_id': payment.id,
            'view_mode': 'form',
            'target': 'current',
        }
