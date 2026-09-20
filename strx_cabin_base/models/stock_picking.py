# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    strx_has_cabin_content = fields.Boolean(
        string='Contains Cabin Content',
        compute='_compute_strx_has_cabin_content',
        store=True,
        index=True)

    @api.depends('move_ids.product_id.strx_is_cabin')
    def _compute_strx_has_cabin_content(self):
        for picking in self:
            picking.strx_has_cabin_content = any(
                move.product_id.strx_is_cabin for move in picking.move_ids)
