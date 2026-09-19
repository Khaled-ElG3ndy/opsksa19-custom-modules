# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero


class StrxSaleQuantityIncreaseWizard(models.TransientModel):
    _name = 'strx.sale.quantity.increase.wizard'
    _description = 'Quantity Increase Wizard'

    original_order_id = fields.Many2one(
        'sale.order', string='Original Order', required=True, readonly=True)
    line_ids = fields.One2many(
        'strx.sale.quantity.increase.wizard.line', 'wizard_id',
        string='Requested Increases')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order_id = res.get('original_order_id') or self.env.context.get(
            'default_original_order_id') or self.env.context.get('active_id')
        order = self.env['sale.order'].browse(order_id).exists()
        if order:
            res['original_order_id'] = order.id
            cabin_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id.strx_is_cabin)
            res['line_ids'] = [(0, 0, {
                'order_line_id': line.id,
                'increase_qty': 0.0,
                'price_unit': line.price_unit,
            }) for line in cabin_lines]
        return res

    def _strx_sale_order_values(self):
        self.ensure_one()
        order = self.original_order_id
        SaleOrder = self.env['sale.order']
        vals = {
            'partner_id': order.partner_id.id,
            'strx_origin_order_id': order.id,
            'origin': order.name,
            'client_order_ref': _(
                "Quantity increase for %(order)s", order=order.name),
        }
        for field_name in (
            'partner_invoice_id', 'partner_shipping_id', 'pricelist_id',
            'payment_term_id', 'user_id', 'team_id', 'company_id',
            'fiscal_position_id', 'warehouse_id', 'analytic_account_id',
        ):
            if field_name in SaleOrder._fields:
                value = order[field_name]
                if value:
                    vals[field_name] = value.id
        return vals

    def action_create_increase_order(self):
        self.ensure_one()
        order = self.original_order_id
        if order.state not in ('sale', 'done'):
            raise UserError(_(
                "Quantity increases are only created from confirmed rental orders."))

        increase_lines = self.line_ids.filtered(
            lambda l: not float_is_zero(
                l.increase_qty,
                precision_rounding=l.product_uom_id.rounding or 0.01))
        if not increase_lines:
            raise UserError(_("Enter at least one increase quantity."))

        sale_vals = self._strx_sale_order_values()
        sale_vals['order_line'] = [
            (0, 0, line._strx_sale_order_line_values())
            for line in increase_lines
        ]
        new_order = self.env['sale.order'].create(sale_vals)
        order.message_post(body=_(
            "Quantity increase order %(new_order)s was created.",
            new_order=new_order.display_name))
        new_order.message_post(body=_(
            "Created as a quantity increase for %(order)s.",
            order=order.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quantity Increase Order'),
            'res_model': 'sale.order',
            'res_id': new_order.id,
            'view_mode': 'form',
            'target': 'current',
        }


class StrxSaleQuantityIncreaseWizardLine(models.TransientModel):
    _name = 'strx.sale.quantity.increase.wizard.line'
    _description = 'Quantity Increase Wizard Line'

    wizard_id = fields.Many2one(
        'strx.sale.quantity.increase.wizard', required=True, ondelete='cascade')
    order_line_id = fields.Many2one(
        'sale.order.line', string='Original Line', required=True,
        readonly=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product',
        related='order_line_id.product_id', readonly=True)
    current_qty = fields.Float(
        string='Current Quantity',
        related='order_line_id.product_uom_qty', readonly=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure',
        related='order_line_id.product_uom_id', readonly=True)
    increase_qty = fields.Float(string='Increase Quantity', default=0.0)
    price_unit = fields.Float(string='Unit Price')

    def _strx_sale_order_line_values(self):
        self.ensure_one()
        precision = self.product_uom_id.rounding or 0.01
        if float_is_zero(self.increase_qty, precision_rounding=precision) \
                or self.increase_qty < 0:
            raise UserError(_("Increase quantity must be greater than zero."))
        line = self.order_line_id
        vals = {
            'product_id': line.product_id.id,
            'product_uom_qty': self.increase_qty,
            'price_unit': self.price_unit,
            'name': _(
                "%(description)s\nAdditional quantity for %(order)s",
                description=line.name,
                order=line.order_id.name),
        }
        if 'product_uom_id' in line._fields and line.product_uom_id:
            vals['product_uom_id'] = line.product_uom_id.id
        for field_name in ('customer_lead', 'discount'):
            if field_name in line._fields:
                vals[field_name] = line[field_name]
        if 'tax_id' in line._fields:
            vals['tax_id'] = [(6, 0, line.tax_id.ids)]
        return vals
