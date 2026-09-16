# Copyright 2026 Khaled ElGendy
# License OPL-1.

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    print_kitchen_notes_receipt = fields.Boolean(
        string="Order Note on Receipt",
        default=True,
        help="Display the order note on preparation receipts.",
    )
