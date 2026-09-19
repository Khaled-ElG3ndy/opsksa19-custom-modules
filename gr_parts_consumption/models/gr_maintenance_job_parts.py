# -*- coding: utf-8 -*-
from odoo import api, fields, models


class GrMaintenanceJobParts(models.Model):
    _inherit = 'gr.maintenance.job'

    parts_line_ids = fields.One2many(
        'gr.parts.consumption.line', 'job_id', string='Parts Used')
    total_parts_cost = fields.Monetary(
        string='Total Parts Cost', currency_field='currency_id',
        compute='_compute_total_parts_cost', store=True)
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, string='Currency')
    # Separate compute from total_parts_cost: a stored and a non-stored field
    # sharing one compute makes reading the count recompute and write the
    # stored total (Odoo 19 warns about this).
    parts_line_count = fields.Integer(
        string='Parts Lines', compute='_compute_parts_line_count')

    @api.depends('parts_line_ids.subtotal_cost', 'parts_line_ids.state')
    def _compute_total_parts_cost(self):
        for job in self:
            consumed = job.parts_line_ids.filtered(
                lambda l: l.state == 'consumed')
            job.total_parts_cost = sum(consumed.mapped('subtotal_cost'))

    @api.depends('parts_line_ids')
    def _compute_parts_line_count(self):
        for job in self:
            job.parts_line_count = len(job.parts_line_ids)
