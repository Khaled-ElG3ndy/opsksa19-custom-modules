# -*- coding: utf-8 -*-
from odoo import fields, models, _


class GrRentalOrderRecurring(models.Model):
    """Where this order came from.

    Purely a back-reference. Nothing about the rental workflow changes because
    an order was prepared from a recurring arrangement: it is confirmed,
    reserved, inspected and dispatched exactly like one typed by hand.
    """
    _inherit = 'gr.rental.order'

    recurring_rental_id = fields.Many2one(
        'gr.recurring.rental', string='Recurring Rental', index=True,
        readonly=True, copy=False, ondelete='set null',
        help="The recurring arrangement this order was prepared from, if any.")

    def action_view_recurring_rental(self):
        self.ensure_one()
        if not self.recurring_rental_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recurring Rental'),
            'res_model': 'gr.recurring.rental',
            'res_id': self.recurring_rental_id.id,
            'view_mode': 'form',
        }
