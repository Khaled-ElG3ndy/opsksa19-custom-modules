# -*- coding: utf-8 -*-
from odoo import fields, models


class StrxCabinHistoryEvent(models.TransientModel):
    """Readable, on-demand timeline rows for one physical cabin/serial."""
    _name = 'strx.cabin.history.event'
    _description = 'Cabin History Event'
    _order = 'event_date desc, id desc'
    _rec_name = 'title'

    lot_id = fields.Many2one('stock.lot', string='Serial', readonly=True)
    event_date = fields.Datetime(string='Date', readonly=True)
    event_type = fields.Selection(
        selection=[
            ('readiness', 'Readiness Change'),
            ('allocation', 'Allocation'),
            ('shipment', 'Shipment'),
        ],
        string='Type',
        readonly=True)
    title = fields.Char(string='Event', readonly=True)
    reference = fields.Char(string='Reference', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    details = fields.Text(string='Details', readonly=True)
