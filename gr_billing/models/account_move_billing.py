# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', readonly=True, copy=False,
        index=True, ondelete='set null')


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    rental_asset_type = fields.Char(
        string='Type', readonly=True, copy=False,
        help="Type of the rented serial copied from the rental order line.")
    rental_equipment_reference = fields.Char(
        string='Equipment Reference', readonly=True, copy=False,
        help="Equipment number copied from the rental order line for audit "
             "and printed invoice descriptions.")
