# Copyright 2026 Khaled ElGendy
# All rights reserved.

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    print_kitchen_receipt = fields.Boolean(
        string="Print Kitchen Receipt",
        default=False,
    )
    print_kitchen_receipt_categ = fields.Boolean(
        string="Enable Category Wise Receipt",
        default=False,
    )
    print_kitchen_categories_exclude_ids = fields.Many2many(
        comodel_name="product.category",
        relation="kitchen_print_category_rel",
        column1="config_id",
        column2="category_id",
        string="Exclude Categories on Print",
        help="Products from these categories are omitted from category-wise kitchen receipts.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    print_kitchen_receipt = fields.Boolean(
        related="pos_config_id.print_kitchen_receipt",
        readonly=False,
        string="Print Kitchen Receipt",
    )
    print_kitchen_receipt_categ = fields.Boolean(
        related="pos_config_id.print_kitchen_receipt_categ",
        readonly=False,
        string="Enable Category Wise Receipt",
    )
    print_kitchen_categories_exclude_ids = fields.Many2many(
        related="pos_config_id.print_kitchen_categories_exclude_ids",
        readonly=False,
        string="Exclude Categories on Print",
    )

