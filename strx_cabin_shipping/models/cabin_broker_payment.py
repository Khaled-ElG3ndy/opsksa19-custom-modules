# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StrxCabinBrokerPayment(models.Model):
    """Operational payment order for shipping brokers.

    This is deliberately logistics-owned: it groups delivered shipments for a
    broker and records issuance/approval/payment status without changing Odoo
    Accounting data or requiring Accounting modules.
    """
    _name = 'strx.cabin.broker.payment'
    _description = 'Broker Payment Order'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(
        string='Payment Order', required=True, copy=False, readonly=True,
        index=True, default=lambda self: _('New'))
    broker_id = fields.Many2one(
        'strx.cabin.broker', string='Broker', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        required=True)
    payment_batch = fields.Selection(
        selection=[
            ('single', 'Single Shipment'),
            ('broker_batch', 'Broker Batch'),
            ('weekly', 'Weekly Batch'),
            ('monthly', 'Monthly Batch'),
            ('custom', 'Custom Period'),
        ],
        string='Batch Option', default='broker_batch', required=True,
        tracking=True)
    date_from = fields.Date(string='From Date')
    date_to = fields.Date(string='To Date')
    due_date = fields.Date(string='Due Date')
    issue_date = fields.Datetime(string='Issued On', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    paid_date = fields.Datetime(string='Paid On', readonly=True, copy=False)
    issued_by_id = fields.Many2one(
        'res.users', string='Issued By', readonly=True, copy=False)
    approved_by_id = fields.Many2one(
        'res.users', string='Approved By', readonly=True, copy=False)
    paid_by_id = fields.Many2one(
        'res.users', string='Paid By', readonly=True, copy=False)
    payment_reference = fields.Char(string='Payment Reference')
    shipping_order_ids = fields.Many2many(
        'strx.cabin.shipping.order',
        'strx_cabin_broker_payment_shipping_order_rel',
        'payment_id', 'shipping_order_id',
        string='Shipments')
    eligible_shipping_order_ids = fields.Many2many(
        'strx.cabin.shipping.order',
        compute='_compute_eligible_shipping_orders',
        string='Eligible Shipments')
    waybill_count = fields.Integer(
        string='Shipment Count', compute='_compute_totals', store=True)
    amount_total = fields.Monetary(
        string='Total Amount', currency_field='currency_id',
        compute='_compute_totals', store=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('issued', 'Issued'),
            ('approved', 'Approved'),
            ('paid', 'Paid'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, copy=False,
        tracking=True)
    note = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'strx.cabin.broker.payment') or _('New')
        payments = super().create(vals_list)
        payments._strx_validate_payment_order()
        return payments

    def write(self, vals):
        locked_fields = {
            'broker_id', 'shipping_order_ids', 'payment_batch', 'date_from',
            'date_to', 'currency_id',
        }
        if locked_fields & set(vals):
            locked = self.filtered(lambda p: p.state not in ('draft', 'cancel'))
            if locked:
                raise UserError(_(
                    "You can only change broker, shipments, batch option, period, "
                    "or currency while the payment order is Draft."))
        res = super().write(vals)
        if locked_fields & set(vals):
            self._strx_validate_payment_order()
        return res

    @api.depends('broker_id', 'date_from', 'date_to', 'shipping_order_ids')
    def _compute_eligible_shipping_orders(self):
        for payment in self:
            payment.eligible_shipping_order_ids = payment._strx_payable_waybills()

    @api.depends('shipping_order_ids.agreed_cost', 'shipping_order_ids.state')
    def _compute_totals(self):
        for payment in self:
            live = payment.shipping_order_ids.filtered(
                lambda w: w.state != 'cancel')
            payment.waybill_count = len(live)
            payment.amount_total = sum(live.mapped('agreed_cost'))

    @api.onchange('broker_id')
    def _onchange_broker_id(self):
        for payment in self:
            if payment.broker_id:
                payment.currency_id = (
                    payment.broker_id.currency_id or payment.currency_id)

    def _strx_other_active_payment_domain(self):
        self.ensure_one()
        return [
            ('id', '!=', self.id),
            ('state', '!=', 'cancel'),
        ]

    def _strx_payable_waybills(self):
        self.ensure_one()
        domain = [
            ('state', '=', 'delivered'),
            ('agreed_cost', '>', 0),
            ('company_id', '=', self.company_id.id),
        ]
        if self.broker_id:
            domain.append(('broker_id', '=', self.broker_id.id))
        if self.date_from:
            domain.append(('delivered_date', '>=', fields.Datetime.to_datetime(
                self.date_from)))
        if self.date_to:
            to_dt = fields.Datetime.to_datetime(self.date_to)
            domain.append(('delivered_date', '<', fields.Datetime.add(
                to_dt, days=1)))
        waybills = self.env['strx.cabin.shipping.order'].search(domain)
        used = self.env['strx.cabin.broker.payment'].search(
            self._strx_other_active_payment_domain()).mapped('shipping_order_ids')
        return waybills - used

    def _strx_validate_payment_order(self):
        Payment = self.env['strx.cabin.broker.payment']
        for payment in self:
            waybills = payment.shipping_order_ids
            if not waybills:
                continue
            brokers = waybills.mapped('broker_id')
            if len(brokers) != 1 or brokers != payment.broker_id:
                raise ValidationError(_(
                    "All shipments in a payment order must belong to the selected broker."))
            if any(w.state != 'delivered' for w in waybills):
                raise ValidationError(_(
                    "Only delivered shipments can be added to a broker payment order."))
            if any(w.agreed_cost <= 0 for w in waybills):
                raise ValidationError(_(
                    "All shipments in a broker payment order must have an agreed cost."))
            if any(w.company_id != payment.company_id for w in waybills):
                raise ValidationError(_(
                    "All shipments must belong to the same company as the payment order."))
            if len(waybills.mapped('currency_id')) > 1:
                raise ValidationError(_(
                    "All shipments in one payment order must use the same currency."))
            if waybills and payment.currency_id != waybills[0].currency_id:
                raise ValidationError(_(
                    "The payment currency must match the shipment currency."))
            duplicate = Payment.search([
                ('id', '!=', payment.id),
                ('state', '!=', 'cancel'),
                ('shipping_order_ids', 'in', waybills.ids),
            ], limit=1)
            if duplicate:
                duplicated = duplicate.shipping_order_ids & waybills
                raise ValidationError(_(
                    "These shipments are already included in payment order %(payment)s: %(shipments)s",
                    payment=duplicate.display_name,
                    shipments=", ".join(duplicated.mapped('name'))))

    def action_fill_payable_waybills(self):
        for payment in self:
            if not payment.broker_id:
                raise UserError(_("Select a broker first."))
            waybills = payment._strx_payable_waybills()
            if not waybills:
                raise UserError(_("No due delivered shipments were found for this broker."))
            payment.write({'shipping_order_ids': [(6, 0, waybills.ids)]})

    def action_issue(self):
        for payment in self:
            payment._strx_validate_payment_order()
            if not payment.shipping_order_ids:
                raise UserError(_("Add at least one delivered shipment before issuing the payment order."))
            if payment.amount_total <= 0:
                raise UserError(_("The payment order total must be greater than zero."))
        self.write({
            'state': 'issued',
            'issue_date': fields.Datetime.now(),
            'issued_by_id': self.env.user.id,
        })

    def action_approve(self):
        self.write({
            'state': 'approved',
            'approved_date': fields.Datetime.now(),
            'approved_by_id': self.env.user.id,
        })

    def action_mark_paid(self):
        self.write({
            'state': 'paid',
            'paid_date': fields.Datetime.now(),
            'paid_by_id': self.env.user.id,
        })

    def action_cancel(self):
        paid = self.filtered(lambda p: p.state == 'paid')
        if paid:
            raise UserError(_("Paid payment orders cannot be cancelled."))
        self.write({'state': 'cancel'})

    def action_reset_to_draft(self):
        paid = self.filtered(lambda p: p.state == 'paid')
        if paid:
            raise UserError(_("Paid payment orders cannot be reset to Draft."))
        self.write({'state': 'draft'})
