# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class POSTimeslot(models.Model):
    _name = 'pos.timeslot'
    _description = 'POS Timeslot'

    name = fields.Char('Name')
    time_from = fields.Float('From')
    time_to = fields.Float('To')

    def decimal_to_time(self, decimal):
        hours = int(decimal)  # Get the integer part (hours)
        minutes = (decimal - hours) * 60  # Get the fractional part, convert it to minutes
        return hours, round(minutes)

    @api.constrains('time_from', 'time_to')
    def check_for_overlapping_of_time(self):
        all_time_slots = self.sudo().search([])
        for rec in self:
            for timeslot in all_time_slots:
                if timeslot.id != rec.id:
                    if timeslot.time_from <= rec.time_from <= timeslot.time_to:
                        raise ValidationError(_('Time cannot be overlapped!'))
                    if timeslot.time_from <= rec.time_to <= timeslot.time_to:
                        raise ValidationError(_('Time cannot be overlapped!'))



