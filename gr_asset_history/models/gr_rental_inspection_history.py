# -*- coding: utf-8 -*-
from odoo import api, models, _

from .rental_asset_history import history_text


class GrRentalInspectionHistory(models.Model):
    _inherit = 'gr.rental.inspection'

    def _history_record(self, event_type, title, description=False):
        History = self.env['rental.asset.history']
        for insp in self:
            targets = []
            if hasattr(insp.rental_order_id, '_history_targets'):
                targets = insp.rental_order_id._history_targets()
            elif insp.asset_id:
                targets = [('asset', insp.asset_id)]
            for kind, target in targets:
                event_title = title
                if event_type == 'inspection_created':
                    event_title = history_text(
                        self.env,
                        _('Inspection created for %(asset)s'),
                        asset=target.display_name)
                elif event_type == 'inspection_passed':
                    event_title = history_text(
                        self.env,
                        _('Inspection passed for %(asset)s'),
                        asset=target.display_name)
                elif event_type == 'inspection_failed':
                    event_title = history_text(
                        self.env,
                        _('Inspection failed for %(asset)s'),
                        asset=target.display_name)
                elif event_type == 'damage_found':
                    event_title = history_text(
                        self.env,
                        _('Damage or issue found on %(asset)s'),
                        asset=target.display_name)
                History.record_event(
                    target,
                    event_type=event_type,
                    name=event_title,
                    description=description or insp.remarks or insp.display_name,
                    partner=insp.partner_id,
                    location=insp.rental_order_id.site_id,
                    location_label=(
                        insp.rental_order_id.site_id.display_name
                        if insp.rental_order_id.site_id else False),
                    event_datetime=insp.inspection_date,
                    technical_key='gr.rental.inspection:%s:%s:%s:%s' % (
                        insp.id, event_type, kind, target.id),
                    source=insp,
                )

    @api.model_create_multi
    def create(self, vals_list):
        inspections = super().create(vals_list)
        inspections._history_record(
            'inspection_created',
            _("Inspection created"),
            _("Rental inspection was created."))
        return inspections

    def action_pass(self):
        res = super().action_pass()
        self._history_record(
            'inspection_passed',
            _("Inspection passed"),
            _("Inspection was passed."))
        return res

    def action_fail(self):
        res = super().action_fail()
        self._history_record(
            'inspection_failed',
            _("Inspection failed"),
            _("Inspection failed. Review checklist notes for damage or issues."))
        self._history_record(
            'damage_found',
            _("Damage or issue found"),
            _("Inspection was marked failed; possible damage or issue recorded."))
        return res
