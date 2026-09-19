# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrMaintenanceJob(models.Model):
    _name = 'gr.maintenance.job'
    _description = 'Generator Maintenance Job'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Job Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Generator Asset', required=True,
        index=True, tracking=True)
    job_type = fields.Selection([
        ('preventive', 'Preventive'),
        ('corrective', 'Corrective'),
        ('breakdown', 'Breakdown'),
    ], string='Type', default='preventive', required=True, tracking=True)
    template_id = fields.Many2one(
        'gr.maintenance.template', string='PM Template')

    technician_id = fields.Many2one('res.users', string='Assigned Technician', tracking=True)
    scheduled_date = fields.Datetime(string='Scheduled', tracking=True, index=True)
    scheduled_end_datetime = fields.Datetime(
        string='Scheduled End', tracking=True, index=True,
        help="Planned end of the unavailable maintenance window. Leave empty "
             "for open-ended downtime until the job is completed.")
    started_date = fields.Datetime(string='Started', readonly=True, copy=False)
    completed_date = fields.Datetime(string='Completed', readonly=True, copy=False)

    meter_at_service = fields.Float(string='Meter at Service')
    labor_hours = fields.Float(string='Labor Hours')
    downtime_hours = fields.Float(string='Downtime Hours')
    work_performed = fields.Text(string='Work Performed')
    parts_note = fields.Text(
        string='Parts Used (note)',
        help="Free-text for now; structured parts consumption arrives with the "
             "stock-integration milestone.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False,
        index=True)

    checklist_ids = fields.One2many(
        'gr.maintenance.job.checklist', 'job_id', string='Checklist')
    reset_pm = fields.Boolean(
        string='Reset PM Clock on Completion', default=True,
        help="When done, set the asset's last PM hour/date to now so the next "
             "PM interval starts fresh. Typically on for preventive jobs.")

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The maintenance-job reference must be unique per company.",
    )

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS gr_maintenance_job_availability_idx
                ON gr_maintenance_job
             (company_id, state, asset_id, scheduled_date, scheduled_end_datetime)
        """)

    @api.constrains('scheduled_date', 'scheduled_end_datetime')
    def _check_scheduled_end_after_start(self):
        for job in self:
            if job.scheduled_date and job.scheduled_end_datetime \
                    and job.scheduled_end_datetime <= job.scheduled_date:
                raise ValidationError(_(
                    "Scheduled End must be after the Scheduled start for %s.")
                    % job.display_name)

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.maintenance.job') or _('New')
        return super().create(vals_list)

    @api.onchange('template_id')
    def _onchange_template(self):
        if self.template_id:
            self.job_type = self.template_id.job_type
            if not self.checklist_ids:
                self.checklist_ids = [(0, 0, {
                    'sequence': l.sequence, 'name': l.name})
                    for l in self.template_id.checklist_line_ids]

    @api.onchange('asset_id')
    def _onchange_asset(self):
        if self.asset_id:
            self.meter_at_service = self.asset_id.current_hour_meter

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_schedule(self):
        for job in self:
            if job.state != 'draft':
                raise UserError(_("Only draft jobs can be scheduled."))
            if not job.scheduled_date:
                raise UserError(_("Set a scheduled date before scheduling."))
            job._check_rental_conflicts_for_maintenance(
                job.scheduled_date, job.scheduled_end_datetime)
            job.state = 'scheduled'
        return True

    def action_start(self):
        for job in self:
            if job.state not in ('draft', 'scheduled'):
                raise UserError(_("Only draft or scheduled jobs can start."))
            if job.asset_id.status == 'retired':
                raise UserError(_("Cannot service a retired asset."))
            if job.asset_id.status == 'on_rent':
                raise UserError(_(
                    "Asset %s is on rent; it must be returned before maintenance.")
                    % job.asset_id.display_name)
            job._check_rental_conflicts_for_maintenance(
                fields.Datetime.now(), job.scheduled_end_datetime)
            job.state = 'in_progress'
            job.started_date = fields.Datetime.now()
            # Move the asset out of service for the duration of the job.
            new_status = 'breakdown' if job.job_type == 'breakdown' else 'under_maintenance'
            job.asset_id.status = new_status
        return True

    def _check_rental_conflicts_for_maintenance(self, start, end=False):
        engine = self.env['gr.rental.availability']
        for job in self:
            conflicts = engine.conflicts_for_targets(
                job.asset_id, start, end, job.company_id)
            order_conflicts = [
                conflict for conflict in conflicts
                if conflict.get('type') == 'order'
            ]
            if order_conflicts:
                raise UserError(_(
                    "Cannot schedule maintenance for %(asset)s during %(period)s "
                    "because the equipment is already committed to a rental.",
                    asset=job.asset_id.display_name,
                    period=engine._format_range(
                        engine._as_datetime(start), engine._as_datetime(end))))
        return True

    def action_complete(self):
        for job in self:
            if job.state != 'in_progress':
                raise UserError(_("Only in-progress jobs can be completed."))
            job.state = 'done'
            job.completed_date = fields.Datetime.now()
            asset = job.asset_id
            # Reset the PM clock if requested (preventive completion).
            if job.reset_pm:
                vals = {'last_pm_date': fields.Date.context_today(job)}
                # last_pm_hour anchors to the meter at service (or current).
                vals['last_pm_hour'] = job.meter_at_service or asset.current_hour_meter
                asset.write(vals)
            # Return the asset to service (clears maintenance_due via recompute).
            if asset.status in ('under_maintenance', 'breakdown', 'maintenance_due'):
                asset.status = 'available'
        return True

    def action_cancel(self):
        for job in self:
            if job.state == 'done':
                raise UserError(_("Completed jobs cannot be cancelled."))
            # If the asset was taken out of service by this job, return it.
            if job.state == 'in_progress' and job.asset_id.status in (
                    'under_maintenance', 'breakdown'):
                job.asset_id.status = 'available'
            job.state = 'cancelled'
        return True

    def action_reset_to_draft(self):
        for job in self:
            if job.state != 'cancelled':
                raise UserError(_("Only cancelled jobs can reset to draft."))
            job.state = 'draft'
        return True


class GrMaintenanceJobChecklist(models.Model):
    _name = 'gr.maintenance.job.checklist'
    _description = 'Generator Maintenance Job Checklist Item'
    _order = 'job_id, sequence, id'

    job_id = fields.Many2one(
        'gr.maintenance.job', string='Job', required=True, ondelete='cascade',
        index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Check Item', required=True)
    is_done = fields.Boolean(string='Done')
    note = fields.Char(string='Note')
