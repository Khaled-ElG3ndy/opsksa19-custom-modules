# -*- coding: utf-8 -*-
"""A smart button on the customer, and nothing else.

The arrangement itself lives on its own record, so the contact form gains one
button rather than a schedule, a line table and a dozen fields that would sit
empty for every customer who does not rent on a cycle.
"""
from odoo import api, fields, models, _


class ResPartnerRecurring(models.Model):
    _inherit = 'res.partner'

    recurring_rental_ids = fields.One2many(
        'gr.recurring.rental', 'partner_id', string='Recurring Rentals')
    recurring_rental_count = fields.Integer(
        string='Recurring Rentals', compute='_compute_recurring_rental_count')
    recurring_rental_alert = fields.Selection([
        ('due_today', 'Recurring Rental Due Today'),
        ('overdue', 'Recurring Rental Overdue'),
    ], string='Recurring Rental Alert',
        compute='_compute_recurring_rental_count',
        help="Set when one of this customer's active arrangements needs "
             "attention, so the contact form shows it without opening the "
             "arrangements.")

    @api.depends('recurring_rental_ids.active',
                 'recurring_rental_ids.occurrence_state')
    def _compute_recurring_rental_count(self):
        counts = dict.fromkeys(self.ids, 0)
        alerts = {}
        Recurring = self.env['gr.recurring.rental']
        if self.ids:
            for partner, state, count in Recurring._read_group(
                    [('partner_id', 'in', self.ids), ('active', '=', True)],
                    ['partner_id', 'occurrence_state'], ['__count']):
                counts[partner.id] = counts.get(partner.id, 0) + count
                # Overdue outranks due-today; anything calmer is not an alert.
                if state == 'overdue':
                    alerts[partner.id] = 'overdue'
                elif state == 'due_today' and alerts.get(partner.id) != 'overdue':
                    alerts[partner.id] = 'due_today'
        for partner in self:
            partner.recurring_rental_count = counts.get(partner.id, 0)
            partner.recurring_rental_alert = alerts.get(partner.id, False)

    def action_view_recurring_rentals(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recurring Rentals'),
            'res_model': 'gr.recurring.rental',
            'domain': [('partner_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_partner_id': self.id},
        }
