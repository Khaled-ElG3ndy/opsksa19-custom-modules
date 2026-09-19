# -*- coding: utf-8 -*-
from odoo import fields, models


class GrHourLogBilling(models.Model):
    _inherit = 'gr.hour.log'

    invoice_id = fields.Many2one(
        'account.move', string='Invoice', readonly=True, copy=False,
        help="The draft invoice that consumed this approved log.")
    billed = fields.Boolean(
        string='Billed', readonly=True, copy=False, default=False,
        help="True once this approved log has been placed on an invoice. "
             "A log is billed at most once.")
