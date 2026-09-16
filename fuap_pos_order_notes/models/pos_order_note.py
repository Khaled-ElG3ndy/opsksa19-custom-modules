# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosOrderNote(models.Model):
    _name = "pos.order.note"
    _description = "Order Notes Tags"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, id"

    name = fields.Char(string="Name", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [("id", "in", config.order_note_ids.ids)]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "sequence"]

