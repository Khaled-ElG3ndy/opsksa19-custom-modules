# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    strx_has_cabin_content = fields.Boolean(
        string='Contains Cabin Content',
        compute='_compute_strx_has_cabin_content',
        store=True,
        index=True)

    @api.depends('invoice_line_ids.strx_is_cabin_line')
    def _compute_strx_has_cabin_content(self):
        for move in self:
            move.strx_has_cabin_content = any(
                line.strx_is_cabin_line for line in move.invoice_line_ids)


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
    strx_is_cabin_line = fields.Boolean(
        string='Cabin Invoice Line',
        compute='_compute_strx_is_cabin_line',
        store=True,
        index=True)

    @api.depends('product_id.strx_is_cabin', 'strx_allocated_lot_ids')
    def _compute_strx_is_cabin_line(self):
        for line in self:
            line.strx_is_cabin_line = bool(
                line.product_id.strx_is_cabin or line.strx_allocated_lot_ids)
