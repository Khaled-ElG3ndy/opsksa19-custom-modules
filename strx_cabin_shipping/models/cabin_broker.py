# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class StrxCabinBroker(models.Model):
    """Shipping provider — the internal group carrier 'We Transport' or an external one."""
    _name = 'strx.cabin.broker'
    _description = 'Cabin Shipping Broker'
    _order = 'is_internal desc, name'

    name = fields.Char(string='Broker', required=True)
    active = fields.Boolean(default=True)
    is_internal = fields.Boolean(
        string='Company Transport',
        help="Group company carrier. Movements are flagged for inter-company treatment.")
    partner_id = fields.Many2one('res.partner', string='Company')
    company_registration = fields.Char(string='CR Number',
                                       help="Commercial Registration number.")
    contact_name = fields.Char(string='Contact')
    contact_phone = fields.Char(string='Phone')
    contact_email = fields.Char(string='Email')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    default_rate = fields.Monetary(string='Default Rate', currency_field='currency_id',
                                   help="Indicative rate per movement.")
    rate_note = fields.Text(string='Rate Notes')
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company,
        help="Leave empty to share this broker with every company.")
    shipping_order_ids = fields.One2many('strx.cabin.shipping.order', 'broker_id',
                                         string='Shipments')
    shipping_order_count = fields.Integer(compute='_compute_shipping_order_count')
    payment_order_ids = fields.One2many(
        'strx.cabin.broker.payment', 'broker_id', string='Payment Orders')
    payment_order_count = fields.Integer(compute='_compute_payment_order_count')

    def _compute_shipping_order_count(self):
        for broker in self:
            broker.shipping_order_count = len(broker.shipping_order_ids)

    def _compute_payment_order_count(self):
        for broker in self:
            broker.payment_order_count = len(broker.payment_order_ids)

    def action_view_payment_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Broker Payment Orders'),
            'res_model': 'strx.cabin.broker.payment',
            'view_mode': 'list,form',
            'domain': [('broker_id', '=', self.id)],
            'context': {'default_broker_id': self.id},
        }

    def action_create_payment_order(self):
        self.ensure_one()
        payment = self.env['strx.cabin.broker.payment'].create({
            'broker_id': self.id,
            'currency_id': (self.currency_id or self.env.company.currency_id).id,
            'payment_batch': 'broker_batch',
        })
        try:
            payment.action_fill_payable_waybills()
        except UserError:
            pass
        return {
            'type': 'ir.actions.act_window',
            'name': _('Broker Payment Order'),
            'res_model': 'strx.cabin.broker.payment',
            'res_id': payment.id,
            'view_mode': 'form',
            'target': 'current',
        }
