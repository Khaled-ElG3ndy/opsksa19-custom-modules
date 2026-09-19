# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    strx_shipping_order_ids = fields.One2many(
        'strx.cabin.shipping.order', 'order_id', string='Shipments')
    strx_shipping_count = fields.Integer(compute='_compute_strx_shipping')
    strx_shipping_cost = fields.Monetary(
        string='Shipping Cost', compute='_compute_strx_shipping',
        currency_field='currency_id',
        help="Total agreed shipping cost booked against this rental, for margin "
             "visibility. Cancelled shipments are excluded.")
    strx_customer_receipt_signature = fields.Image(
        string='Customer Signature / Stamp',
        copy=False,
        attachment=True,
        help="Customer signature or company stamp on the delivery receipt.")
    strx_customer_receipt_attachment_ids = fields.Many2many(
        'ir.attachment',
        'strx_sale_order_receipt_attachment_rel',
        'order_id',
        'attachment_id',
        string='Receipt Attachments',
        copy=False,
        help="Attach the signed/stamped delivery receipt or any supporting proof.")
    strx_customer_receipt_exception = fields.Boolean(
        string='Customer Did Not Sign',
        copy=False,
        tracking=True,
        help="Use only when the customer did not sign or stamp the receipt.")
    strx_customer_receipt_exception_reason = fields.Text(
        string='Exception Reason',
        copy=False,
        tracking=True)

    @api.depends('strx_shipping_order_ids.agreed_cost',
                 'strx_shipping_order_ids.state')
    def _compute_strx_shipping(self):
        for order in self:
            live = order.strx_shipping_order_ids.filtered(
                lambda s: s.state != 'cancel')
            order.strx_shipping_count = len(order.strx_shipping_order_ids)
            order.strx_shipping_cost = sum(live.mapped('agreed_cost'))

    def action_view_strx_shipping_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Shipments'),
            'res_model': 'strx.cabin.shipping.order',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id,
                        'default_partner_id': self.partner_id.id},
        }
