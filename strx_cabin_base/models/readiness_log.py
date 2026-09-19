# -*- coding: utf-8 -*-
from odoo import fields, models

from .constants import CABIN_CONDITIONS, READINESS_STATES


class StrxCabinReadinessLog(models.Model):
    """Append-only, event-driven history of asset readiness transitions.

    One row per state change of a physical cabin (stock.lot). Written automatically
    by stock.lot.write(); not meant to be created or edited by hand.
    """
    _name = 'strx.cabin.readiness.log'
    _description = 'Cabin Readiness Log'
    _order = 'event_date desc, id desc'
    _rec_name = 'lot_id'

    lot_id = fields.Many2one(
        'stock.lot', string='Cabin', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one(
        'product.product', related='lot_id.product_id', store=True, readonly=True)
    old_state = fields.Selection(selection=READINESS_STATES, string='From')
    new_state = fields.Selection(selection=READINESS_STATES, string='To')
    condition = fields.Selection(
        selection=CABIN_CONDITIONS, string='Condition', readonly=True,
        help="Physical condition recorded when this readiness event occurred.")
    reason = fields.Char(string='Reason')
    note = fields.Text(string='Note')
    user_id = fields.Many2one(
        'res.users', string='By', default=lambda self: self.env.user, readonly=True)
    event_date = fields.Datetime(
        string='When', default=fields.Datetime.now, index=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', related='lot_id.company_id',
        store=True, index=True, readonly=True,
        help="Follows the company of the physical cabin, so a readiness event is "
             "only visible to the company that owns the unit.")
