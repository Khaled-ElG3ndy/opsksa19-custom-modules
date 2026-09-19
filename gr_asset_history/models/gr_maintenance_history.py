# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .rental_asset_history import history_text


class GrMaintenanceJobHistory(models.Model):
    _inherit = 'gr.maintenance.job'

    def _history_record(self, event_type, title, description=False,
                        event_datetime=False):
        History = self.env['rental.asset.history']
        for job in self:
            event_title = title
            if event_type == 'maintenance_opened':
                event_title = history_text(
                    self.env,
                    _('Maintenance opened for %(asset)s'),
                    asset=job.asset_id.display_name)
            elif event_type == 'maintenance_scheduled':
                event_title = history_text(
                    self.env,
                    _('Maintenance scheduled for %(asset)s'),
                    asset=job.asset_id.display_name)
            elif event_type == 'maintenance_started':
                event_title = history_text(
                    self.env,
                    _('Maintenance started for %(asset)s'),
                    asset=job.asset_id.display_name)
            elif event_type == 'maintenance_done':
                event_title = history_text(
                    self.env,
                    _('Maintenance completed for %(asset)s'),
                    asset=job.asset_id.display_name)
            elif event_type == 'maintenance_cancelled':
                event_title = history_text(
                    self.env,
                    _('Maintenance cancelled for %(asset)s'),
                    asset=job.asset_id.display_name)
            History.record_event(
                job.asset_id,
                event_type=event_type,
                name=event_title,
                description=description or job.display_name,
                old_state=False,
                new_state=job.state,
                event_datetime=event_datetime,
                technical_key='gr.maintenance.job:%s:%s:asset:%s' % (
                    job.id, event_type, job.asset_id.id),
                source=job,
            )

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        jobs._history_record(
            'maintenance_opened',
            _("Maintenance opened"),
            _("Maintenance job was created."))
        return jobs

    def action_schedule(self):
        res = super().action_schedule()
        self._history_record(
            'maintenance_scheduled',
            _("Maintenance scheduled"),
            _("Maintenance job was scheduled."))
        return res

    def action_start(self):
        res = super().action_start()
        for job in self:
            job.asset_id.with_context(gr_skip_history_asset_write=True).write({
                'current_rental_order_id': False,
                'current_contract_id': False,
                'current_site_id': False,
                'expected_return_datetime': False,
            })
        self._history_record(
            'maintenance_started',
            _("Maintenance started"),
            _("Maintenance job started and the asset was moved out of service."),
            event_datetime=fields.Datetime.now())
        return res

    def action_complete(self):
        res = super().action_complete()
        self._history_record(
            'maintenance_done',
            _("Maintenance completed"),
            _("Maintenance job was completed."),
            event_datetime=fields.Datetime.now())
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._history_record(
            'maintenance_cancelled',
            _("Maintenance cancelled"),
            _("Maintenance job was cancelled."))
        return res
