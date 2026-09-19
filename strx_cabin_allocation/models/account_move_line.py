# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    strx_allocated_lot_ids = fields.Many2many(
        'stock.lot',
        'strx_account_move_line_stock_lot_rel',
        'move_line_id',
        'lot_id',
        string='Allocated Serials',
        copy=False,
        readonly=True,
        help="Cabin serials committed to the related sale-order line when this "
             "invoice line was created.")
    strx_allocated_serial_numbers = fields.Char(
        string='Allocated Serial Numbers',
        copy=False,
        readonly=True,
        help="A permanent snapshot of the allocated cabin serial numbers at "
             "invoice creation time.")
