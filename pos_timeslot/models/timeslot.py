# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class POSTimeslot(models.Model):
    _name = 'pos.timeslot'
    _description = 'POS Timeslot'

    name = fields.Char('Name', required=True)
    time_from = fields.Float('From')
    time_to = fields.Float('To')

    def decimal_to_time(self, decimal):
        hours = int(decimal)  # Get the integer part (hours)
        minutes = (decimal - hours) * 60  # Get the fractional part, convert it to minutes
        return hours, round(minutes)

    @api.constrains('time_from', 'time_to')
    def check_for_overlapping_of_time(self):
        """Slots are half-open ranges, [time_from, time_to).

        Two half-open ranges overlap exactly when each starts before the
        other ends, which is the test used here. The previous version
        compared each bound against the other slot's range instead, so it
        both rejected slots that merely touch (08:00-12:00 next to
        12:00-17:00) and failed to notice a slot that swallows another
        whole (09:00-10:00 inside a new 08:00-11:00).
        """
        for rec in self:
            if not 0.0 <= rec.time_from < rec.time_to <= 24.0:
                raise ValidationError(
                    _('A timeslot must be between 00:00 and 24:00, and '
                      'must end after it starts.'))
            others = self.sudo().search([('id', '!=', rec.id)])
            for other in others:
                if rec.time_from < other.time_to and other.time_from < rec.time_to:
                    raise ValidationError(
                        _('Timeslot "%(new)s" overlaps "%(existing)s".',
                          new=rec.name or '', existing=other.name or ''))
