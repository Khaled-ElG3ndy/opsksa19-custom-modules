# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class ReportPOSOrder(models.Model):
    _inherit = 'report.pos.order'

    pos_timeslot_id = fields.Many2one('pos.timeslot','Timeslot')

    def _select(self):
        return super()._select() + ", s.pos_timeslot_id as pos_timeslot_id"

    # NOTE: report.pos.order.init() on 19 builds the SQL view from
    # _select() + _from() only, and the view carries no GROUP BY at all,
    # so a _group_by() override would be dead code here.

    def _from(self):
        return super()._from() + " LEFT JOIN pos_timeslot pts ON (s.pos_timeslot_id=pts.id)"
