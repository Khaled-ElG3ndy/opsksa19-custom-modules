# Copyright 2026 Khaled ElGendy
# License OPL-1.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    print_kitchen_notes_receipt = fields.Boolean(
        related="pos_config_id.print_kitchen_notes_receipt",
        readonly=False,
    )
