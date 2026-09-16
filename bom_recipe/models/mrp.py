# -*- coding: utf-8 -*-
from odoo import api, fields, models, _, Command
from odoo.exceptions import ValidationError


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    is_recipe = fields.Boolean(string='Is Recipe')
    yield_percentage = fields.Float(string='Yield %', default=0.0)
    # product_qty = fields.Float(
    #     string='Quantity',
    #     compute='_compute_total_product_qty',
    #     readonly=False
    # )
    bom_qty = fields.Float(string='Total Component Quantity', compute='_compute_total_component_qty')

    @api.constrains('bom_line_ids', 'product_uom_id')
    def _check_uom_restriction(self):
        for bom in self:
            if bom.product_uom_id and bom.is_recipe:
                for line in bom.bom_line_ids:
                    if line.product_uom_id and line.product_uom_id != bom.product_uom_id:
                        raise ValidationError(_(
                            "The UoM of the BOM Lines must match the UoM of the BOM."
                            "\nBOM UoM: %s, BOM Line UoM: %s" % (bom.product_uom_id.name, line.product_uom_id.name)
                        ))

    @api.depends('bom_line_ids.product_qty')
    def _compute_total_component_qty(self):
        for bom in self:
            bom.bom_qty = sum(line.product_qty for line in bom.bom_line_ids)

    @api.onchange('bom_qty', 'yield_percentage', 'is_recipe')
    def _onchange_total_product_qty(self):
        if self.is_recipe:
            self.product_qty = self.bom_qty * (1 - self.yield_percentage)
        else:
            self.product_qty = self.product_qty
