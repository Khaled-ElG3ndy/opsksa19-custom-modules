# -*- coding: utf-8 -*-
from odoo import _, fields, models


class StrxCabinAllocation(models.Model):
    _inherit = 'strx.cabin.allocation'

    strx_substitution_ids = fields.One2many(
        'strx.cabin.substitution', 'allocation_id', string='Substitutions')
    strx_substitution_count = fields.Integer(compute='_compute_strx_substitution_count')

    def _compute_strx_substitution_count(self):
        for alloc in self:
            alloc.strx_substitution_count = len(alloc.strx_substitution_ids)

    def action_request_substitution(self):
        """Open a pre-filled substitution request for this allocation."""
        self.ensure_one()
        default_lot = self.lot_ids if len(self.lot_ids) == 1 else self.env['stock.lot']
        return {
            'type': 'ir.actions.act_window',
            'name': _('Request Substitution'),
            'res_model': 'strx.cabin.substitution',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_allocation_id': self.id,
                'default_original_product_id': self.product_id.id,
                'default_original_lot_id': default_lot.id,
                'default_proposed_product_id': self.product_id.id,
            },
        }

    def action_view_strx_substitutions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Substitutions'),
            'res_model': 'strx.cabin.substitution',
            'view_mode': 'list,form',
            'domain': [('allocation_id', '=', self.id)],
            'context': {'default_allocation_id': self.id},
        }
