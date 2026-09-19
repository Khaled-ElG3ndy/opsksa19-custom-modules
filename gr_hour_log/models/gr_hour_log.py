# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class GrHourLog(models.Model):
    _name = 'gr.hour.log'
    _description = 'Generator Hour Log'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'reading_date desc, id desc'

    # Fields that lock once the log is approved; later changes require the
    # audited correction action (mirrors the M3 contract amendment pattern).
    _LOCKED_FIELDS = (
        'reading_date', 'current_meter_reading', 'rental_order_id', 'asset_id')

    name = fields.Char(
        string='Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)

    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', required=True, index=True,
        tracking=True,
        domain="[('state', 'in', ('installed','on_rent','off_hire_requested','returned','inspection','closed'))]")
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Generator Asset', tracking=True,
        index=True, store=True, readonly=True,
        compute='_compute_from_order')
    partner_id = fields.Many2one(
        'res.partner', string='Customer', store=True, readonly=True,
        compute='_compute_from_order')
    contract_id = fields.Many2one(
        'gr.rental.contract', string='Contract', store=True, readonly=True,
        compute='_compute_from_order')

    reading_date = fields.Date(
        string='Reading Date', required=True, tracking=True,
        default=fields.Date.context_today)
    previous_log_id = fields.Many2one(
        'gr.hour.log', string='Previous Log', readonly=True, copy=False)
    previous_meter_reading = fields.Float(
        string='Previous Meter', tracking=True,
        help="Meter at the previous approved reading for this rental "
             "(or the rental start meter if this is the first log).")
    current_meter_reading = fields.Float(
        string='Current Meter', required=True, tracking=True)
    previous_reading_date = fields.Date(string='Previous Reading Date', readonly=True)

    days_covered = fields.Integer(
        string='Days Covered', compute='_compute_hours', store=True,
        help="Whole days between the previous reading date and this one "
             "(minimum 1). Allowances scale by this number.")
    used_hours = fields.Float(
        string='Used Hours', compute='_compute_hours', store=True)
    included_allowance = fields.Float(
        string='Included Allowance', compute='_compute_hours', store=True,
        help="Contract included hours/day x days covered.")
    max_allowance = fields.Float(
        string='Max Allowance', compute='_compute_hours', store=True,
        help="Contract max hours/day x days covered.")
    regular_hours = fields.Float(
        string='Regular Hours', compute='_compute_hours', store=True)
    overtime_hours = fields.Float(
        string='Overtime Hours', compute='_compute_hours', store=True)
    violation_hours = fields.Float(
        string='Violation Hours', compute='_compute_hours', store=True)
    has_violation = fields.Boolean(
        string='Has Violation', compute='_compute_hours', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True,
        copy=False, index=True)

    note = fields.Text(string='Note')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The hour-log reference must be unique per company.",
    )

    # ------------------------------------------------------------------
    @api.depends('rental_order_id')
    def _compute_from_order(self):
        for log in self:
            o = log.rental_order_id
            log.asset_id = o.asset_id
            log.partner_id = o.partner_id
            log.contract_id = o.contract_id

    @api.onchange('rental_order_id')
    def _onchange_rental_order_id_seed_readings(self):
        for log in self:
            if not log.rental_order_id:
                log.previous_log_id = False
                log.previous_meter_reading = 0.0
                log.previous_reading_date = False
                continue
            values = log._get_previous_reading_values()
            log.previous_log_id = values['previous_log_id']
            log.previous_meter_reading = values['previous_meter_reading']
            log.previous_reading_date = values['previous_reading_date']
            order = log.rental_order_id
            if not log.current_meter_reading and order.state in ('returned', 'inspection', 'closed') \
                    and order.end_meter_reading:
                log.current_meter_reading = order.end_meter_reading

    # ------------------------------------------------------------------
    # Core calculation. Allowances scale by whole days covered, derived from
    # the reading dates (not user-entered), so batching readings cannot dodge
    # overtime/violation accounting.
    # ------------------------------------------------------------------
    @api.depends('current_meter_reading', 'previous_meter_reading',
                 'reading_date', 'previous_reading_date',
                 'contract_id.included_hours_per_day',
                 'contract_id.max_hours_per_day')
    def _compute_hours(self):
        for log in self:
            # days covered (>=1)
            days = 1
            if log.reading_date and log.previous_reading_date:
                delta = (log.reading_date - log.previous_reading_date).days
                days = max(1, delta)
            log.days_covered = days

            used = (log.current_meter_reading or 0.0) - (log.previous_meter_reading or 0.0)
            if used < 0:
                used = 0.0
            log.used_hours = used

            inc_day = log.contract_id.included_hours_per_day or 0.0
            max_day = log.contract_id.max_hours_per_day or 0.0
            inc = inc_day * days
            mx = max_day * days
            log.included_allowance = inc
            log.max_allowance = mx

            # regular = min(used, included)
            regular = min(used, inc) if inc else 0.0
            # overtime = portion between included and max
            if mx and mx > inc:
                overtime = max(0.0, min(used, mx) - inc)
            else:
                overtime = 0.0
            # violation = portion above max (if a max is set)
            violation = max(0.0, used - mx) if mx else 0.0

            # If no included set, everything is regular (flat rental, no banding).
            if not inc and not mx:
                regular = used
                overtime = 0.0
                violation = 0.0

            log.regular_hours = regular
            log.overtime_hours = overtime
            log.violation_hours = violation
            log.has_violation = bool(violation > 0.0)

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        seeded_flags = []
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.hour.log') or _('New')
            # Remember whether the caller explicitly supplied previous values;
            # if so, the auto-seed must not overwrite them.
            seeded_flags.append(
                'previous_reading_date' in vals or 'previous_meter_reading' in vals)
        logs = super().create(vals_list)
        for log, supplied in zip(logs, seeded_flags):
            if not supplied:
                log._seed_previous_reading()
        return logs

    def _seed_previous_reading(self):
        """Find the prior approved log for this rental/asset to anchor the
        previous meter + date. Falls back to the rental order's start meter."""
        self.ensure_one()
        if self.previous_log_id:
            return
        values = self._get_previous_reading_values()
        self.previous_log_id = values['previous_log_id']
        self.previous_meter_reading = values['previous_meter_reading']
        self.previous_reading_date = values['previous_reading_date']

    def _get_previous_reading_values(self):
        self.ensure_one()
        prior = self.search([
            ('rental_order_id', '=', self.rental_order_id.id),
            ('state', '=', 'approved'),
            ('id', '!=', self.id),
        ], order='reading_date desc, id desc', limit=1)
        if prior:
            return {
                'previous_log_id': prior.id,
                'previous_meter_reading': prior.current_meter_reading,
                'previous_reading_date': prior.reading_date,
            }
        o = self.rental_order_id
        return {
            'previous_log_id': False,
            'previous_meter_reading': o.start_meter_reading or 0.0,
            'previous_reading_date': (
                o.actual_install_datetime.date()
                if o.actual_install_datetime else False),
        }

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('current_meter_reading', 'previous_meter_reading')
    def _check_meter_not_below_previous(self):
        for log in self:
            if log.current_meter_reading < (log.previous_meter_reading or 0.0):
                raise ValidationError(_(
                    "Current meter (%(cur)s) cannot be below the previous "
                    "reading (%(prev)s).",
                    cur=log.current_meter_reading,
                    prev=log.previous_meter_reading))

    @api.constrains('reading_date', 'previous_reading_date')
    def _check_date_order(self):
        for log in self:
            if log.previous_reading_date and log.reading_date \
                    and log.reading_date < log.previous_reading_date:
                raise ValidationError(_(
                    "Reading date cannot be earlier than the previous reading date."))

    # ------------------------------------------------------------------
    # Approval-lock: locked fields cannot change once approved, except via the
    # audited correction action (which sets the gr_hourlog_correction context).
    # ------------------------------------------------------------------
    def write(self, vals):
        if not self.env.context.get('gr_hourlog_correction'):
            locked = [f for f in self._LOCKED_FIELDS if f in vals]
            if locked:
                for log in self:
                    if log.state == 'approved':
                        raise UserError(_(
                            "Approved hour log %(name)s is locked. Use the "
                            "correction action to change %(fields)s.",
                            name=log.name, fields=', '.join(locked)))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_submit(self):
        for log in self:
            if log.state != 'draft':
                raise UserError(_("Only draft logs can be submitted."))
            if not log.rental_order_id:
                raise UserError(_("A rental order is required."))
            log.state = 'submitted'
            if log.has_violation:
                log._raise_violation_alert()
        return True

    def action_approve(self):
        for log in self:
            if log.state != 'submitted':
                raise UserError(_("Only submitted logs can be approved."))
            # Violation gate: only Ops Manager / GM / Admin may approve a log
            # that breaches the contracted maximum.
            if log.has_violation and not (
                    self.env.user.has_group('gr_security_base.group_generator_operations_officer')
                    or self.env.user.has_group('gr_security_base.group_generator_general_manager')
                    or self.env.user.has_group('gr_security_base.group_generator_administrator')):
                raise UserError(_(
                    "Hour log %s breaches the contracted maximum and can only "
                    "be approved by an Operations Manager or General Manager.")
                    % log.name)
            log.state = 'approved'
            log.approved_by_id = self.env.user.id
            log.approved_date = fields.Datetime.now()
            log._apply_to_asset()
        return True

    def action_cancel(self):
        for log in self:
            if log.state == 'approved':
                raise UserError(_(
                    "Approved logs cannot be cancelled; use a correction instead."))
            log.state = 'cancelled'
        return True

    def action_reset_to_draft(self):
        for log in self:
            if log.state not in ('submitted', 'cancelled'):
                raise UserError(_("Only submitted or cancelled logs can reset to draft."))
            log.state = 'draft'
        return True

    # ------------------------------------------------------------------
    def _apply_to_asset(self):
        """On approval, advance the asset meter (never roll back) and flip it to
        Maintenance Due if it crosses its PM threshold — instead of rejecting
        the reading. This is the production-correct transition."""
        self.ensure_one()
        asset = self.asset_id
        if not asset:
            return
        new_meter = self.current_meter_reading
        if new_meter <= (asset.current_hour_meter or 0.0):
            return  # nothing to advance
        crosses_pm = bool(
            asset.pm_interval_hours and asset.next_pm_hour
            and new_meter >= asset.next_pm_hour)
        vals = {'current_hour_meter': new_meter}
        # Move out of 'available' to 'maintenance_due' if crossing PM while
        # available, so the asset-level constraint (available != overdue) holds.
        if crosses_pm and asset.status == 'available':
            vals['status'] = 'maintenance_due'
        asset.with_context(gr_meter_correction=True).write(vals)
        if crosses_pm:
            asset.message_post(
                body=_("Hour log %(log)s pushed the meter to %(m)s h, crossing "
                       "the PM threshold (%(pm)s h). Maintenance is now due.",
                       log=self.name, m=new_meter, pm=asset.next_pm_hour),
                message_type='comment', subtype_xmlid='mail.mt_note')

    def _raise_violation_alert(self):
        """Raise an activity to Operations and Sales managers when a log breaches
        the contracted maximum."""
        self.ensure_one()
        groups = [
            'gr_security_base.group_generator_operations_officer',
            'gr_security_base.group_generator_sales_officer',
        ]
        user_ids = set()
        for xmlid in groups:
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                user_ids.update(grp.user_ids.ids)
        try:
            activity_type = self.env.ref('mail.mail_activity_data_warning')
            act_type_id = activity_type.id
        except Exception:
            act_type_id = False
        for uid in user_ids:
            self.activity_schedule(
                act_type_xmlid='mail.mail_activity_data_warning'
                if act_type_id else 'mail.mail_activity_data_todo',
                user_id=uid,
                summary=_("Hour-log violation: %s") % self.name,
                note=_("Generator %(asset)s logged %(v)s violation hour(s) over "
                       "the contracted maximum on %(d)s.",
                       asset=self.asset_id.display_name or '',
                       v=self.violation_hours, d=self.reading_date))
        self.message_post(
            body=_("Violation alert raised to Operations and Sales: %s hour(s) "
                   "over the contracted maximum.") % self.violation_hours,
            message_type='comment', subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    def action_open_correction(self):
        """Open a guided correction wizard for an approved log."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Only approved logs can be corrected."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Correct Hour Log'),
            'res_model': 'gr.hour.log.correction.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_log_id': self.id},
        }
