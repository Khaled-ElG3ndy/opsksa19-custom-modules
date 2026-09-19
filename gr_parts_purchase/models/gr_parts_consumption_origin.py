# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class GrPartsConsumptionLineOrigin(models.Model):
    """Add the purchase-to-install origin link to the M8 consumption line, so
    'installed on X' connects back to 'ordered for X'."""
    _inherit = 'gr.parts.consumption.line'

    request_id = fields.Many2one(
        'gr.parts.request', string='Source Request', index=True,
        domain="[('state', 'in', ('draft', 'issued', 'purchased', 'received')), "
               "('qty_remaining_to_issue', '>', 0)]",
        help="The parts request this consumption fulfils. Links the part "
             "installed on the unit back to the purchase raised for it.")
    purchase_line_id = fields.Many2one(
        'purchase.order.line', related='request_id.purchase_line_id',
        store=True, readonly=True, string='Origin PO Line')
    request_remaining_qty = fields.Float(
        string='Remaining Quantity', related='request_id.qty_remaining_to_issue',
        readonly=True)
    allowed_product_ids = fields.Many2many(
        'product.product', string='Allowed Parts',
        compute='_compute_allowed_product_ids')

    @api.depends('request_id', 'request_id.product_id')
    def _compute_allowed_product_ids(self):
        Product = self.env['product.product']
        for line in self:
            if line.request_id and line.request_id.product_id:
                line.allowed_product_ids = line.request_id.product_id
            else:
                line.allowed_product_ids = Product.search([
                    ('is_storable', '=', True)])

    @api.model
    def _values_from_request(self, vals):
        req_id = vals.get('request_id')
        if not req_id:
            return vals
        vals = dict(vals)
        req = self.env['gr.parts.request'].browse(req_id)
        if req.exists():
            vals.setdefault('job_id', req.job_id.id)
            vals.setdefault('product_id', req.product_id.id)
            vals.setdefault('warehouse_id', req.warehouse_id.id)
            vals.setdefault('source_location_id', req.source_location_id.id)
            if 'quantity' not in vals or not vals.get('quantity'):
                vals['quantity'] = req.qty_remaining_to_issue
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._values_from_request(vals) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        vals = self._values_from_request(vals)
        return super().write(vals)

    @api.onchange('request_id')
    def _onchange_request_id(self):
        for line in self:
            req = line.request_id
            if not req:
                return {'domain': {'product_id': [('is_storable', '=', True)]}}
            line.job_id = req.job_id
            line.product_id = req.product_id
            line.warehouse_id = req.warehouse_id
            line.source_location_id = req.source_location_id
            line.quantity = req.qty_remaining_to_issue
            line.unit_cost = req.product_id.standard_price
            return {'domain': {'product_id': [('id', '=', req.product_id.id)]}}

    @api.constrains('request_id', 'job_id', 'product_id')
    def _check_request_matches_consumption(self):
        for line in self:
            req = line.request_id
            if not req:
                continue
            if line.job_id and line.job_id != req.job_id:
                raise ValidationError(_(
                    "Maintenance Job must match the selected Source Request."))
            if line.product_id and line.product_id != req.product_id:
                raise ValidationError(_(
                    "Part must match the selected Source Request."))

    def _request_remaining_excluding_self(self):
        self.ensure_one()
        if not self.request_id:
            return 0.0
        consumed = self.request_id.consumption_line_ids.filtered(
            lambda line: line.state == 'consumed' and line != self)
        return max(0.0, (self.request_id.quantity or 0.0)
                   - sum(consumed.mapped('quantity')))

    def _check_request_quantity_available(self):
        for line in self:
            if not line.request_id:
                continue
            if line.request_id.state not in (
                    'draft', 'issued', 'purchased', 'received'):
                raise UserError(_(
                    "Source Request %s is not open for issuing parts.")
                    % line.request_id.display_name)
            remaining = line._request_remaining_excluding_self()
            if line.quantity > remaining:
                raise UserError(_(
                    "Cannot issue %(qty)s %(uom)s from request %(req)s. "
                    "Remaining quantity is %(remaining)s %(uom)s.",
                    qty=line.quantity,
                    remaining=remaining,
                    uom=line.product_uom_id.display_name or '',
                    req=line.request_id.display_name))

    def action_consume(self):
        self._check_request_quantity_available()
        res = super().action_consume()
        # After a successful issue, refresh request counters.
        for line in self:
            if line.request_id and line.state == 'consumed':
                line.request_id.invalidate_recordset([
                    'qty_issued', 'qty_remaining_to_issue',
                    'qty_shortage_to_buy', 'available_qty'])
        return res
