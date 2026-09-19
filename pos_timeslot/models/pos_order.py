# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import pytz

class POSOrder(models.Model):
    _inherit = 'pos.order'

    pos_timeslot_id = fields.Many2one('pos.timeslot','Timeslot',)

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        slots = self.env['pos.timeslot'].sudo().search([], order='time_from')
        if slots:
            for rec in res:
                rec.pos_timeslot_id = rec._match_timeslot(slots).id
        return res

    def _match_timeslot(self, slots):
        """Return the slot covering the moment this order is created.

        Slots are half-open, [time_from, time_to), so 08:00-12:00 and
        12:00-17:00 sit next to each other without both claiming noon.
        """
        self.ensure_one()
        now = self._timeslot_local_time()
        now_decimal = now.hour + now.minute / 60.0 + now.second / 3600.0
        for slot in slots:
            if slot.time_from <= now_decimal < slot.time_to:
                return slot
        return self.env['pos.timeslot']

    def _timeslot_local_time(self):
        """Wall-clock time to compare the slots against.

        fields.Datetime.now() is naive UTC. Calling .astimezone() on a naive
        value makes Python assume the server's local zone, so attach UTC
        first and only then convert.
        """
        self.ensure_one()
        now_utc = pytz.utc.localize(fields.Datetime.now())
        tz_name = self.user_id.tz or self.env.user.tz or 'UTC'
        return now_utc.astimezone(pytz.timezone(tz_name))

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


