# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
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
                            "\nBOM UoM: %(bom_uom)s, BOM Line UoM: %(line_uom)s",
                            bom_uom=bom.product_uom_id.name,
                            line_uom=line.product_uom_id.name,
                        ))

    @api.constrains('is_recipe', 'yield_percentage')
    def _check_yield_percentage(self):
        """A recipe must always produce a strictly positive quantity.

        The percentage widget stores 25% as ``0.25``.  Values below zero
        increase the output and values at or above 100% make Odoo's required
        BoM quantity zero/negative, so neither is a valid recipe yield loss.
        """
        for bom in self:
            if bom.is_recipe and not 0.0 <= bom.yield_percentage < 1.0:
                raise ValidationError(_(
                    "Recipe yield loss must be at least 0%% and less than 100%%."
                ))

    @api.depends('bom_line_ids.product_qty')
    def _compute_total_component_qty(self):
        for bom in self:
            bom.bom_qty = sum(line.product_qty for line in bom.bom_line_ids)

    @api.onchange('bom_qty', 'yield_percentage', 'is_recipe')
    def _onchange_total_product_qty(self):
        if self.is_recipe:
            self.product_qty = self.bom_qty * (1 - self.yield_percentage)


class MrpBomLine(models.Model):
    """Re-check the recipe UoM rule when a line is edited on its own.

    ``@api.constrains`` ignores dotted names, so the rule declared on
    ``mrp.bom`` for ``bom_line_ids`` only fires when the lines are written
    through the parent -- which is what the BoM form does, and what an import or
    an API call writing straight to ``mrp.bom.line`` does not. Without this the
    rule holds in the interface and quietly does not hold anywhere else.
    """
    _inherit = 'mrp.bom.line'

    @api.constrains('product_uom_id')
    def _check_recipe_uom_matches_its_bom(self):
        self.bom_id._check_uom_restriction()
