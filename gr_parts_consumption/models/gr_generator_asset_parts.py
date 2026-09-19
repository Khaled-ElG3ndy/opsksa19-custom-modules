# -*- coding: utf-8 -*-
from odoo import models


class GrGeneratorAssetParts(models.Model):
    _inherit = 'gr.generator.asset'

    def _compute_live_metrics(self):
        # Run the base (M9) computation first to populate utilization, revenue,
        # open_job_count, and the placeholder cost/profit.
        super()._compute_live_metrics()
        # Now make cost REAL: sum consumed-parts cost across the asset's done/
        # in-progress maintenance jobs, and recompute the profit estimate.
        for asset in self:
            parts_cost = 0.0
            for job in asset.maintenance_job_ids:
                parts_cost += job.total_parts_cost or 0.0
            asset.live_cost = parts_cost
            asset.live_profit_estimate = asset.live_revenue - asset.live_cost
