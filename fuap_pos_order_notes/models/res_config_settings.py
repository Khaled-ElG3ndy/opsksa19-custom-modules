# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_order_note_on_receipt = fields.Boolean(
        related="pos_config_id.order_note_on_receipt",
        readonly=False,
    )
    pos_order_note_ids = fields.Many2many(
        related="pos_config_id.order_note_ids",
        readonly=False,
    )

