# -*- coding: utf-8 -*-
from odoo import api, models, _


class GrFieldWorksheetHistory(models.Model):
    _inherit = 'gr.field.worksheet'

    def _history_record(self, event_type, title, description=False):
        History = self.env['rental.asset.history']
        for worksheet in self.filtered('asset_id'):
            History.record_event(
                worksheet.asset_id,
                event_type=event_type,
                name=title,
                description=description or worksheet.remarks or worksheet.display_name,
                partner=worksheet.partner_id,
                location_label=worksheet.location,
                event_datetime=worksheet.verified_on or worksheet.time_out or worksheet.time_in,
                technical_key='gr.field.worksheet:%s:%s:asset:%s' % (
                    worksheet.id, event_type, worksheet.asset_id.id),
                source=worksheet,
            )

    @api.model_create_multi
    def create(self, vals_list):
        worksheets = super().create(vals_list)
        worksheets._history_record(
            'visit_created',
            _("Visit / worksheet created"),
            _("Field worksheet was created."))
        return worksheets

    def action_submit(self):
        res = super().action_submit()
        self._history_record(
            'visit_submitted',
            _("Visit / worksheet submitted"),
            _("Field worksheet was submitted."))
        return res

    def action_verify(self):
        res = super().action_verify()
        self._history_record(
            'visit_verified',
            _("Visit / worksheet verified"),
            _("Field worksheet was verified with required proof."))
        return res
