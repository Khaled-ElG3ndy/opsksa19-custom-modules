# -*- coding: utf-8 -*-
from odoo import fields, models


class PartnerDocumentCategory(models.Model):
    _name = 'partner.document.category'
    _description = 'Partner Document Category'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(
        help="Stable technical key, so that other modules can reference a "
             "category without depending on its translated name.",
    )
    color = fields.Integer(string='Color Index', default=0)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint('unique(code)', "A document category code must be unique.")
