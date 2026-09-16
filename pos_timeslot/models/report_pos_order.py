# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class ReportPOSOrder(models.Model):
    _inherit = 'report.pos.order'

    pos_timeslot_id = fields.Many2one('pos.timeslot','Timeslot')

    def _select(self):
        return super()._select() + ", s.pos_timeslot_id as pos_timeslot_id"

    def _group_by(self):
        return super()._group_by() + ", s.pos_timeslot_id"

    def _from(self):
        return super()._from() + " LEFT JOIN pos_timeslot pts ON (s.pos_timeslot_id=pts.id)"
