# -*- coding: utf-8 -*-
from odoo import api, fields, models


class GrGeneratorAssetMaintenance(models.Model):
    _inherit = 'gr.generator.asset'

    # Calendar-based PM (complements the hour-based PM from gr_fleet_base).
    pm_interval_days = fields.Integer(
        string='PM Interval (days)',
        help="Calendar interval for preventive maintenance. PM becomes due when "
             "either the hour interval OR this calendar interval is reached, "
             "whichever comes first. Leave 0 to disable calendar PM.")
    last_pm_date = fields.Date(
        string='Last PM Date', tracking=True)
    next_pm_date = fields.Date(
        string='Next PM Date', compute='_compute_next_pm_date', store=True)
    pm_calendar_overdue = fields.Boolean(
        string='Calendar PM Overdue', compute='_compute_pm_calendar_overdue',
        store=True)

    maintenance_job_ids = fields.One2many(
        'gr.maintenance.job', 'asset_id', string='Maintenance Jobs')
    maintenance_job_count = fields.Integer(
        string='Jobs', compute='_compute_maintenance_job_count')

    @api.depends('last_pm_date', 'pm_interval_days')
    def _compute_next_pm_date(self):
        from dateutil.relativedelta import relativedelta
        for asset in self:
            if asset.last_pm_date and asset.pm_interval_days:
                asset.next_pm_date = asset.last_pm_date + relativedelta(
                    days=asset.pm_interval_days)
            else:
                asset.next_pm_date = False

    @api.depends('next_pm_date')
    def _compute_pm_calendar_overdue(self):
        today = fields.Date.context_today(self)
        for asset in self:
            asset.pm_calendar_overdue = bool(
                asset.next_pm_date and asset.next_pm_date <= today)

    # Broaden the base hour-based overdue flag to ALSO trip on calendar PM.
    # Preserves the exact hour behaviour (calendar term is False when unset).
    @api.depends('current_hour_meter', 'next_pm_hour', 'pm_interval_hours',
                 'pm_calendar_overdue')
    def _compute_maintenance_overdue(self):
        for asset in self:
            hour_overdue = bool(
                asset.pm_interval_hours and asset.next_pm_hour
                and asset.current_hour_meter >= asset.next_pm_hour)
            asset.maintenance_overdue = bool(
                hour_overdue or asset.pm_calendar_overdue)

    def _compute_maintenance_job_count(self):
        Job = self.env['gr.maintenance.job']
        for asset in self:
            asset.maintenance_job_count = Job.search_count(
                [('asset_id', '=', asset.id)])

    def action_view_maintenance_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Maintenance Jobs',
            'res_model': 'gr.maintenance.job',
            'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }

    # Daily cron: flag assets whose calendar PM is due, moving an available
    # asset to maintenance_due (mirrors the hour-based auto-transition in M5).
    @api.model
    def _cron_flag_calendar_pm_due(self):
        today = fields.Date.context_today(self)
        due = self.search([
            ('pm_interval_days', '>', 0),
            ('next_pm_date', '!=', False),
            ('next_pm_date', '<=', today),
            ('status', '=', 'available'),
        ])
        for asset in due:
            asset.status = 'maintenance_due'
            asset.message_post(
                body="Calendar PM is due (next PM date %s). Asset moved to "
                     "Maintenance Due." % asset.next_pm_date,
                message_type='comment', subtype_xmlid='mail.mt_note')
        return True
