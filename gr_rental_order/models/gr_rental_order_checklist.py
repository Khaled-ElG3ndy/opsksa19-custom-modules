# -*- coding: utf-8 -*-
from odoo import fields, models


class GrRentalOrderChecklist(models.Model):
    _name = 'gr.rental.order.checklist'
    _description = 'Generator Rental Order Checklist Item'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    phase = fields.Selection([
        ('dispatch', 'Dispatch'),
        ('installation', 'Installation'),
        ('commissioning', 'Commissioning'),
        ('return', 'Return'),
        ('safety', 'Safety'),
    ], string='Phase', default='installation', required=True)
    name = fields.Char(string='Check Item', required=True)
    is_done = fields.Boolean(string='Done')
    notes = fields.Char(string='Notes')
