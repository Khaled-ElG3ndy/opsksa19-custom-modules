# -*- coding: utf-8 -*-
from odoo import models, _


class GrPartsConsumptionLineHistory(models.Model):
    _inherit = 'gr.parts.consumption.line'

    def action_consume(self):
        res = super().action_consume()
        History = self.env['rental.asset.history']
        for line in self:
            History.record_event(
                line.asset_id,
                event_type='parts_used',
                name=_("Parts used"),
                description=_(
                    "%(qty)s %(uom)s of %(part)s consumed on maintenance job %(job)s.",
                    qty=line.quantity,
                    uom=line.product_uom_id.display_name,
                    part=line.product_id.display_name,
                    job=line.job_id.display_name),
                technical_key='gr.parts.consumption.line:%s:parts_used:asset:%s' % (
                    line.id, line.asset_id.id),
                source=line,
            )
        return res
