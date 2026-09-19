# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrHourLogCorrectionWizard(models.TransientModel):
    _name = 'gr.hour.log.correction.wizard'
    _description = 'Hour Log Correction'

    log_id = fields.Many2one(
        'gr.hour.log', string='Hour Log', required=True, readonly=True)
    current_meter_reading = fields.Float(
        string='Corrected Current Meter', required=True)
    reading_date = fields.Date(string='Corrected Reading Date', required=True)
    reason = fields.Text(string='Reason', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        log = self.env['gr.hour.log'].browse(res.get('log_id') or
                                              self.env.context.get('default_log_id'))
        if log:
            res.setdefault('current_meter_reading', log.current_meter_reading)
            res.setdefault('reading_date', log.reading_date)
        return res

    def action_apply(self):
        self.ensure_one()
        log = self.log_id
        if log.state != 'approved':
            raise UserError(_("Only approved logs can be corrected."))
        old_meter = log.current_meter_reading
        old_date = log.reading_date
        # Apply via the bypass context so the approval-lock allows it.
        log.with_context(gr_hourlog_correction=True).write({
            'current_meter_reading': self.current_meter_reading,
            'reading_date': self.reading_date,
        })
        log.message_post(
            body=_("Correction applied. Meter %(om)s -> %(nm)s; date %(od)s -> "
                   "%(nd)s. Reason: %(r)s",
                   om=old_meter, nm=self.current_meter_reading,
                   od=old_date, nd=self.reading_date, r=self.reason),
            message_type='comment', subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.act_window_close'}
