# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import pytz
from datetime import datetime

class POSOrder(models.Model):
    _inherit = 'pos.order'

    pos_timeslot_id = fields.Many2one('pos.timeslot','Timeslot',)

    @api.model_create_multi
    def create(self, vals_list):
        res = super(POSOrder, self).create(vals_list)
        for rec in res:
            all_time_slots = self.env['pos.timeslot'].sudo().search([])
            hour_flag = 0
            minute_flag = 0
            for timeslot in all_time_slots:
                current_time = fields.Datetime.now()
                if rec.user_id and rec.user_id.tz:
                    current_time = current_time.astimezone(pytz.timezone(rec.user_id.tz))
                from_hour, from_minute = timeslot.decimal_to_time(timeslot.time_from)
                to_hour, to_minute = timeslot.decimal_to_time(timeslot.time_to)
                if from_hour <= current_time.hour <= to_hour:
                    hour_flag = 1
                if from_minute <= current_time.minute <= to_minute:
                    minute_flag = 1
                if hour_flag and minute_flag:
                    rec.pos_timeslot_id = timeslot.id
                    break
        return res

    # @api.depends('date_order')
    # def _compute_assign_timeslot_based_on_date(self):
    #     all_time_slots = self.env['pos.timeslot'].sudo().search([])
    #     for rec in self:
    #         rec.pos_timeslot_id = False
    #         if rec.date_order:
    #             hour_flag = 0
    #             minute_flag = 0
    #             for timeslot in all_time_slots:
    #                 from_hour, from_minute = timeslot.decimal_to_time(timeslot.time_from)
    #                 to_hour, to_minute = timeslot.decimal_to_time(timeslot.time_to)
    #                 if from_hour <= rec.date_order.hour <= to_hour:
    #                     hour_flag = 1
    #                 if from_minute <= rec.date_order.minute <= to_minute:
    #                     minute_flag = 1
    #                 if hour_flag and minute_flag:
    #                     rec.pos_timeslot_id = timeslot.id
    #                     break


