# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    """Cabin commercial specification.

    Each commercial variant is a DISTINCT product (CAB-5X3-STD, CAB-5X5-VIP, …) —
    never one generic 'Cabin' with a quantity. These fields describe *what spec was
    promised*, so later modules can compare 'same spec vs different spec' when a
    substitution is requested and can render the translated dispatch-block message.
    """
    _inherit = 'product.template'

    strx_is_cabin = fields.Boolean(
        string='Controlled Cabin Asset',
        help="Tick for products whose serial units are governed by cabin fulfillment "
             "control (spec lock, readiness states, dispatch checks).")
    strx_is_free_additional_service = fields.Boolean(
        string='Additional Product',
        help="Tick for add-on products or services requested with a cabin, such as "
             "a bathroom tank, ladder, canopy, AC unit, or water tank. These items "
             "are offered in the Additional Products tab and are not cabin assets.")
    strx_asset_kind = fields.Selection(
        selection=[
            ('cabin', 'Cabin'),
            ('bathroom', 'Bathroom Unit'),
        ],
        string='Asset Kind', default='cabin')
    strx_cabin_size = fields.Selection(
        selection=[
            ('5x3', '5×3'),
            ('5x5', '5×5'),
        ],
        string='Cabin Size')
    strx_cabin_grade = fields.Selection(
        selection=[
            ('std', 'Standard'),
            ('vip', 'VIP'),
        ],
        string='Cabin Grade')
    strx_length_m = fields.Float(string='Nominal Length (m)', digits=(6, 2))
    strx_width_m = fields.Float(string='Nominal Width (m)', digits=(6, 2))

    # Human-readable spec label, e.g. "Cabin 5×3 VIP" — reused in block/substitution text.
    strx_cabin_spec = fields.Char(
        string='Specification', compute='_compute_strx_cabin_spec', store=True)

    @api.depends('name', 'strx_is_cabin', 'strx_asset_kind',
                 'strx_cabin_size', 'strx_cabin_grade')
    def _compute_strx_cabin_spec(self):
        kind_labels = dict(self._fields['strx_asset_kind'].selection)
        size_labels = dict(self._fields['strx_cabin_size'].selection)
        grade_labels = dict(self._fields['strx_cabin_grade'].selection)
        for tmpl in self:
            if not tmpl.strx_is_cabin:
                tmpl.strx_cabin_spec = False
                continue
            parts = [kind_labels.get(tmpl.strx_asset_kind) or 'Cabin']
            if tmpl.strx_cabin_size:
                parts.append(size_labels.get(tmpl.strx_cabin_size))
            if tmpl.strx_cabin_grade:
                parts.append(grade_labels.get(tmpl.strx_cabin_grade))
            tmpl.strx_cabin_spec = ' '.join(p for p in parts if p)
