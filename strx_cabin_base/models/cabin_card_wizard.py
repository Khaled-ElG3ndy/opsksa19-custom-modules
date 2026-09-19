# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CabinIdCardWizard(models.TransientModel):
    _name = 'strx.cabin.id.card.wizard'
    _description = 'Cabin Card Preview'

    lot_id = fields.Many2one(
        'stock.lot', string='Serial', required=True, readonly=True)
    preview_html = fields.Html(
        string='Preview', compute='_compute_preview_html',
        sanitize=False, readonly=True)

    @api.depends(
        'lot_id',
        'lot_id.name',
        'lot_id.strx_barcode',
        'lot_id.product_id',
        'lot_id.strx_cabin_spec',
        'lot_id.strx_readiness_state',
        'lot_id.strx_condition',
        'lot_id.strx_length_m',
        'lot_id.strx_width_m',
    )
    @api.depends_context('lang')
    def _compute_preview_html(self):
        for wizard in self:
            wizard.preview_html = (
                wizard.lot_id.strx_get_cabin_card_preview_html()
                if wizard.lot_id else False
            )

    def action_download(self):
        self.ensure_one()
        return self.lot_id.action_strx_download_cabin_card()
