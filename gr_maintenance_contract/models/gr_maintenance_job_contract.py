# -*- coding: utf-8 -*-
from odoo import fields, models


class GrMaintenanceJobContract(models.Model):
    """Tag maintenance jobs that belong to a maintenance contract, and mark
    whether the visit is covered by the contract or billable T&M."""
    _inherit = 'gr.maintenance.job'

    maintenance_contract_id = fields.Many2one(
        'gr.maintenance.contract', string='Maintenance Contract', index=True,
        help="If set, this visit belongs to a customer maintenance contract.")
    contract_coverage = fields.Selection([
        ('covered', 'Covered (in contract)'),
        ('tm', 'T&M (billable)'),
    ], string='Coverage', help="Covered periodic visit vs out-of-scope "
                               "emergency / time-and-materials work.")
    oil_filter_due = fields.Boolean(
        string='Oil + Filters Due',
        help="This scheduled visit falls on the oil/filter consumable cadence.")
    tm_charge = fields.Monetary(
        string='T&M Charge', currency_field='company_currency_id',
        help="Charge for an out-of-scope emergency / T&M visit.")
    company_currency_id = fields.Many2one(
        'res.currency', string='Company Currency',
        related='company_id.currency_id', readonly=True)
