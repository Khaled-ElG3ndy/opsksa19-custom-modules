# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GrSubletDirectCost(models.Model):
    _name = 'gr.sublet.direct.cost'
    _description = 'Sublet Direct Cost'
    _order = 'cost_date desc, id desc'

    name = fields.Char(string='Description', required=True, default=lambda self: _('Direct Cost'))
    agreement_id = fields.Many2one(
        'gr.sublet.agreement', string='Sublet Agreement', required=True,
        ondelete='cascade', index=True)
    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order',
        domain="[('sublet_agreement_id', '=', agreement_id)]",
        help="Optional: link this cost to the exact customer rental order.")
    cost_date = fields.Date(
        string='Cost Date', required=True, default=fields.Date.context_today)
    cost_type = fields.Selection([
        ('maintenance', 'Maintenance'),
        ('repair', 'Repair'),
        ('parts', 'Parts'),
        ('vendor_bill', 'Vendor Bill / Expense'),
        ('other', 'Other'),
    ], string='Cost Type', default='maintenance', required=True)
    amount = fields.Monetary(string='Amount', required=True)
    company_id = fields.Many2one(
        'res.company', string='Company', related='agreement_id.company_id',
        store=True, readonly=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency', related='agreement_id.currency_id',
        readonly=True)
    note = fields.Text(string='Notes')

    @api.onchange('rental_order_id')
    def _onchange_rental_order_id(self):
        for cost in self:
            if cost.rental_order_id and cost.rental_order_id.sublet_agreement_id:
                cost.agreement_id = cost.rental_order_id.sublet_agreement_id

    @api.constrains('amount')
    def _check_amount(self):
        for cost in self:
            if cost.amount < 0:
                raise ValidationError(_("Direct cost amount cannot be negative."))

    @api.constrains('agreement_id', 'rental_order_id')
    def _check_order_matches_agreement(self):
        for cost in self:
            if cost.rental_order_id and cost.rental_order_id.sublet_agreement_id != cost.agreement_id:
                raise ValidationError(_(
                    "Rental order %(order)s is not linked to sublet agreement %(agreement)s.",
                    order=cost.rental_order_id.display_name,
                    agreement=cost.agreement_id.display_name))
