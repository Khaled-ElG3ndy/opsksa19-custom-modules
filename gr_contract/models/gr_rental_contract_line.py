# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GrRentalContractLine(models.Model):
    _name = 'gr.rental.contract.line'
    _description = 'Generator Rental Contract Allocation Line'
    _order = 'contract_id, id'

    contract_id = fields.Many2one(
        'gr.rental.contract', string='Contract', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='contract_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(
        related='contract_id.currency_id', store=True, string='Currency')
    product_id = fields.Many2one('product.product', string='Product')
    kva_rating = fields.Float(string='kVA Rating')
    quantity = fields.Float(string='Quantity', default=1.0)
    preferred_asset_id = fields.Many2one(
        'gr.generator.asset', string='Preferred Asset')
    rate_override = fields.Monetary(string='Rate Override', currency_field='currency_id')
    notes = fields.Char(string='Notes')

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Allocation quantity must be greater than zero."))
