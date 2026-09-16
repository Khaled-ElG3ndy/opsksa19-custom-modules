# -*- coding: utf-8 -*-
from odoo import api, models


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        models_to_load = super()._load_pos_data_models(config)
        if "pos.order.note" not in models_to_load:
            models_to_load.append("pos.order.note")
        return models_to_load

