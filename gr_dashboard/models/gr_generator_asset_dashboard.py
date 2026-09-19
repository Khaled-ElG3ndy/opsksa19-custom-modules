# -*- coding: utf-8 -*-
from odoo import fields, models


class GrGeneratorAssetDashboard(models.Model):
    _inherit = 'gr.generator.asset'

    # New, separately-named LIVE metrics for dashboards. The M1 placeholder
    # fields (revenue_total / cost_total / profitability) are intentionally left
    # untouched so the existing fleet behaviour and tests are unaffected.
    # These computes read live from approved hour logs and generated invoices.
    live_utilization_hours = fields.Float(
        string='Live Utilization (h)', compute='_compute_live_metrics',
        readonly=True)
    live_revenue = fields.Monetary(
        string='Live Revenue', currency_field='currency_id',
        compute='_compute_live_metrics', readonly=True)
    live_cost = fields.Monetary(
        string='Live Cost', currency_field='currency_id',
        compute='_compute_live_metrics', readonly=True,
        help="Labor/maintenance cost. Parts cost is added by the parts-"
             "consumption milestone; until then this reflects labor only (0).")
    live_profit_estimate = fields.Monetary(
        string='Live Profit (est.)', currency_field='currency_id',
        compute='_compute_live_metrics', readonly=True,
        help="Live revenue minus cost. Cost is labor-only until parts "
             "integration, so this is an upper-bound estimate for now.")
    open_job_count = fields.Integer(
        string='Open Maintenance Jobs', compute='_compute_live_metrics',
        readonly=True)

    def _compute_live_metrics(self):
        HourLog = self.env['gr.hour.log']
        for asset in self:
            logs = HourLog.search([
                ('asset_id', '=', asset.id), ('state', '=', 'approved')])
            asset.live_utilization_hours = sum(logs.mapped('used_hours'))
            invoices = logs.mapped('invoice_id').filtered(
                lambda m: m.state != 'cancel')
            asset.live_revenue = sum(invoices.mapped('amount_untaxed'))
            asset.live_cost = 0.0  # labor-only placeholder until M8 parts
            asset.live_profit_estimate = asset.live_revenue - asset.live_cost
            asset.open_job_count = len(asset.maintenance_job_ids.filtered(
                lambda j: j.state in ('draft', 'scheduled', 'in_progress')))
