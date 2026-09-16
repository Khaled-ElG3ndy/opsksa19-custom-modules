# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    order_note_on_receipt = fields.Boolean(
        string="Order Note on Receipt",
        default=True,
        help="Display order notes on POS receipts.",
    )
    order_note_ids = fields.Many2many(
        "pos.order.note",
        "pos_config_order_note_rel",
        "config_id",
        "note_id",
        string="Order Notes Tags",
        help="Predefined notes available from the Order Note popup.",
    )

