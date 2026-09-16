# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose the Point of Sale default customer on the settings page."""
    _inherit = 'res.config.settings'

    pos_default_customer_id = fields.Many2one(
        'res.partner',
        related='pos_config_id.default_customer_id',
        string="Default Customer",
        readonly=False,
    )
