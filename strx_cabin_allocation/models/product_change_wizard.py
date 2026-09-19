# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StrxSaleProductChangeWizard(models.TransientModel):
    _name = 'strx.sale.product.change.wizard'
    _description = 'Cabin Product Change Wizard'

    original_order_id = fields.Many2one(
        'sale.order', string='Original Order', required=True, readonly=True)
    line_ids = fields.One2many(
        'strx.sale.product.change.wizard.line', 'wizard_id',
        string='Cabin Lines')
    reason = fields.Text(string='Reason')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order_id = res.get('original_order_id') or self.env.context.get(
            'default_original_order_id') or self.env.context.get('active_id')
        order = self.env['sale.order'].browse(order_id).exists()
        if order:
            res['original_order_id'] = order.id
            cabin_lines = order.order_line.filtered(
                lambda line: not line.display_type and line.product_id.strx_is_cabin)
            res['line_ids'] = [(0, 0, {
                'order_line_id': line.id,
                'proposed_product_id': line.product_id.id,
            }) for line in cabin_lines]
        return res

    def action_apply_product_change(self):
        self.ensure_one()
        order = self.original_order_id
        if order.state not in ('sale', 'done'):
            raise UserError(_(
                "Cabin product changes are only available on confirmed rental orders."))
        changed_lines = self.line_ids.filtered(
            lambda line: line.proposed_product_id
            and line.proposed_product_id != line.current_product_id)
        if not changed_lines:
            raise UserError(_("Choose at least one new cabin product."))
        if not self.reason:
            raise UserError(_("Enter the reason for changing the cabin product."))

        for wizard_line in changed_lines:
            sale_line = wizard_line.order_line_id
            sale_line.invalidate_recordset(['product_updatable'])
            sale_line.with_context(
                strx_allow_confirmed_cabin_spec_change=True,
                strx_spec_change_reason=self.reason,
            ).write({'product_id': wizard_line.proposed_product_id.id})

        order.message_post(body=_(
            "Cabin product/specification change applied by %(user)s. Reason: %(reason)s",
            user=self.env.user.display_name,
            reason=self.reason))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'sticky': False,
                'message': _('Cabin product change applied and logistics notified.'),
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


class StrxSaleProductChangeWizardLine(models.TransientModel):
    _name = 'strx.sale.product.change.wizard.line'
    _description = 'Cabin Product Change Wizard Line'

    wizard_id = fields.Many2one(
        'strx.sale.product.change.wizard', required=True, ondelete='cascade')
    order_line_id = fields.Many2one(
        'sale.order.line', string='Sales Order Line',
        readonly=True, ondelete='set null')
    current_product_id = fields.Many2one(
        'product.product', string='Current Product',
        related='order_line_id.product_id', readonly=True)
    proposed_product_id = fields.Many2one(
        'product.product', string='New Product',
        domain="[('strx_is_cabin', '=', True), ('sale_ok', '=', True)]")

    @api.constrains('proposed_product_id')
    def _check_proposed_product_is_cabin(self):
        for line in self:
            if line.proposed_product_id and not line.proposed_product_id.strx_is_cabin:
                raise UserError(_("The new product must be a cabin product."))
