# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import format_date


class GrRentalContract(models.Model):
    _name = 'gr.rental.contract'
    _description = 'Generator Rental Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    # Commercial fields that become locked once the contract is approved.
    # Any change must go through the amendment workflow. Enforced server-side
    # in write() below, not merely in the UI.
    _LOCKED_COMMERCIAL_FIELDS = {
        'contract_type', 'included_hours_per_day', 'max_hours_per_day',
        'base_daily_rate', 'base_monthly_rate', 'hourly_rate',
        'overtime_hour_rate', 'violation_hour_rate', 'standby_rate',
        'operator_daily_rate', 'fuel_billing_policy', 'fuel_rate',
        'mobilization_charge', 'demobilization_charge', 'security_deposit',
        'currency_id', 'partner_id', 'site_id',
    }
    _LOCKED_STATES = {'approved', 'active', 'suspended', 'expired', 'closed'}

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Contract Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True, index=True)
    site_id = fields.Many2one(
        'gr.customer.site', string='Site', tracking=True,
        domain="[('partner_id', '=', partner_id)]")
    sales_user_id = fields.Many2one(
        'res.users', string='Sales Responsible', tracking=True,
        default=lambda self: self._default_sales_responsible_user(),
        help="The salesperson who receives the monthly renewal and invoicing "
             "follow-up activity.")
    active = fields.Boolean(default=True)

    date_start = fields.Date(string='Start Date', tracking=True)
    date_end = fields.Date(string='End Date', tracking=True)

    contract_type = fields.Selection([
        ('hourly', 'Hourly'),
        ('daily_with_included_hours', 'Daily with Included Hours'),
        ('monthly_with_included_hours', 'Monthly with Included Hours'),
        ('standby_plus_usage', 'Standby + Usage'),
    ], string='Contract Type', default='daily_with_included_hours',
        required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False,
        index=True)

    # ------------------------------------------------------------------
    # Commercial terms
    # ------------------------------------------------------------------
    included_hours_per_day = fields.Float(string='Included Hours / Day', tracking=True)
    max_hours_per_day = fields.Float(string='Max Hours / Day', tracking=True)
    base_daily_rate = fields.Monetary(string='Base Daily Rate', currency_field='currency_id')
    base_monthly_rate = fields.Monetary(string='Base Monthly Rate', currency_field='currency_id')
    hourly_rate = fields.Monetary(string='Hourly Rate', currency_field='currency_id')
    overtime_hour_rate = fields.Monetary(string='Overtime Hour Rate', currency_field='currency_id')
    violation_hour_rate = fields.Monetary(string='Violation Hour Rate', currency_field='currency_id')
    standby_rate = fields.Monetary(string='Standby Rate', currency_field='currency_id')
    operator_daily_rate = fields.Monetary(string='Operator Daily Rate', currency_field='currency_id')

    fuel_billing_policy = fields.Selection([
        ('customer_supply', 'Customer Supplies Fuel'),
        ('company_supply_bill_actual', 'Company Supplies - Bill Actual'),
        ('company_supply_fixed_rate', 'Company Supplies - Fixed Rate'),
        ('included', 'Fuel Included'),
    ], string='Fuel Policy', default='customer_supply', tracking=True)
    fuel_rate = fields.Monetary(string='Fuel Rate', currency_field='currency_id')

    mobilization_charge = fields.Monetary(string='Mobilization Charge', currency_field='currency_id')
    demobilization_charge = fields.Monetary(string='Demobilization Charge', currency_field='currency_id')
    security_deposit = fields.Monetary(string='Security Deposit', currency_field='currency_id')

    payment_terms_id = fields.Many2one('account.payment.term', string='Payment Terms')
    customer_po_number = fields.Char(string='Customer PO Number')
    customer_po_attachment = fields.Binary(string='Customer PO Attachment')
    customer_po_filename = fields.Char(string='PO Filename')
    sla_response_hours = fields.Float(string='SLA Response (h)')
    maintenance_included = fields.Boolean(string='Maintenance Included')
    spare_parts_included = fields.Boolean(string='Spare Parts Included')
    requires_daily_customer_signature = fields.Boolean(
        string='Requires Daily Customer Signature')
    sales_monthly_reminder_enabled = fields.Boolean(
        string='Monthly Sales Reminder', default=True, tracking=True,
        help="Raise one activity every month for the sales responsible to "
             "review contract renewal and coordinate the customer invoice.")
    sales_monthly_reminder_day = fields.Integer(
        string='Monthly Reminder Day', default=1, tracking=True,
        help="Day of each month when the sales follow-up becomes due. Keep it "
             "between 1 and 28 so every month has that day.")
    renewal_reminder_days = fields.Integer(
        string='Renewal Lead Time (days)', default=30, tracking=True,
        help="When the contract end date is within this many days, the monthly "
             "activity explicitly calls out renewal.")
    last_sales_followup_period = fields.Char(
        string='Last Sales Follow-up Month', readonly=True, copy=False)

    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account')
    terms_and_conditions = fields.Html(string='Terms & Conditions')
    notes = fields.Text(string='Notes')

    line_ids = fields.One2many(
        'gr.rental.contract.line', 'contract_id', string='Allocation Lines')
    amendment_ids = fields.One2many(
        'gr.contract.amendment', 'contract_id', string='Amendments')
    amendment_count = fields.Integer(compute='_compute_amendment_count')

    # ------------------------------------------------------------------
    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The contract reference must be unique per company.",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.model
    def _default_sales_responsible_user(self):
        group = self.env.ref(
            'gr_security_base.group_generator_sales_officer',
            raise_if_not_found=False)
        if group:
            user = group.user_ids.filtered(lambda usr: usr.active)[:1]
            if user:
                return user
        return self.env.user

    def _compute_amendment_count(self):
        for c in self:
            c.amendment_count = len(c.amendment_ids)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('included_hours_per_day', 'max_hours_per_day')
    def _check_hours(self):
        for c in self:
            if c.included_hours_per_day and c.included_hours_per_day < 0:
                raise ValidationError(_("Included hours per day cannot be negative."))
            if c.max_hours_per_day and c.max_hours_per_day < 0:
                raise ValidationError(_("Max hours per day cannot be negative."))
            if c.max_hours_per_day and c.included_hours_per_day and \
                    c.max_hours_per_day < c.included_hours_per_day:
                raise ValidationError(_(
                    "Max hours per day (%(maxh)s) must be greater than or equal to "
                    "included hours per day (%(inc)s).",
                    maxh=c.max_hours_per_day, inc=c.included_hours_per_day))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for c in self:
            if c.date_start and c.date_end and c.date_end < c.date_start:
                raise ValidationError(_("End date cannot be before the start date."))

    @api.constrains('sales_monthly_reminder_day')
    def _check_sales_monthly_reminder_day(self):
        for c in self:
            if not 1 <= c.sales_monthly_reminder_day <= 28:
                raise ValidationError(_(
                    "Monthly Reminder Day must be between 1 and 28 for %s.")
                    % c.display_name)

    @api.constrains('renewal_reminder_days')
    def _check_renewal_reminder_days(self):
        for c in self:
            if c.renewal_reminder_days < 0:
                raise ValidationError(_(
                    "Renewal Lead Time cannot be negative for %s.")
                    % c.display_name)

    @api.onchange('partner_id')
    def _onchange_partner_sales_user(self):
        if self.partner_id and self.partner_id.user_id and not self.sales_user_id:
            self.sales_user_id = self.partner_id.user_id

    # ------------------------------------------------------------------
    # Create: assign sequence reference
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Partner = self.env['res.partner']
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('gr.rental.contract')
                vals['name'] = seq or _('New')
            if not vals.get('sales_user_id') and vals.get('partner_id'):
                partner = Partner.browse(vals['partner_id'])
                if partner.user_id:
                    vals['sales_user_id'] = partner.user_id.id
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Monthly sales reminders
    # ------------------------------------------------------------------
    @api.model
    def _sales_followup_period(self, today=None):
        today = today or fields.Date.context_today(self)
        return '%04d-%02d' % (today.year, today.month)

    def _sales_followup_user(self):
        self.ensure_one()
        return (
            self.sales_user_id
            or self.partner_id.user_id
            or self._default_sales_responsible_user()
        )

    def _sales_followup_summary(self, period):
        self.ensure_one()
        return _("Monthly sales follow-up: %s") % period

    def _sales_followup_note(self, period, today=None):
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        lines = [
            _("Review contract %(contract)s for %(customer)s.",
              contract=self.display_name,
              customer=self.partner_id.display_name),
            _("Period: %s") % period,
            _("Renew the contract if the customer will continue."),
            _("Issue or coordinate the monthly customer invoice once the "
              "billing period is ready."),
        ]
        if self.date_end:
            days_left = (self.date_end - today).days
            if days_left < 0:
                lines.append(_(
                    "Contract ended on %(date)s. Renew it or close it.",
                    date=format_date(self.env, self.date_end)))
            elif days_left <= self.renewal_reminder_days:
                lines.append(_(
                    "Contract ends on %(date)s (%(days)s day(s) left).",
                    date=format_date(self.env, self.date_end),
                    days=days_left))
        return '<br/>'.join(lines)

    def _existing_sales_followup_activities(self, period):
        self.ensure_one()
        return self.env['mail.activity'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('summary', '=', self._sales_followup_summary(period)),
        ])

    def _schedule_monthly_sales_followup_activity(self, today=None):
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        period = self._sales_followup_period(today)
        if self._existing_sales_followup_activities(period):
            return False
        user = self._sales_followup_user()
        if not user:
            return False
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=self._sales_followup_summary(period),
            note=self._sales_followup_note(period, today=today),
            date_deadline=today,
            user_id=user.id,
        )
        self.message_post(body=_(
            "Monthly sales follow-up reminder raised for %(user)s (%(period)s).",
            user=user.display_name, period=period))
        return True

    def action_raise_monthly_sales_followup(self):
        today = fields.Date.context_today(self)
        period = self._sales_followup_period(today)
        for contract in self:
            if contract.state not in ('approved', 'active'):
                raise UserError(_(
                    "Only approved or active contracts can receive monthly "
                    "sales follow-up reminders."))
            if not contract.sales_monthly_reminder_enabled:
                raise UserError(_(
                    "Monthly Sales Reminder is disabled for %s.")
                    % contract.display_name)
            contract._schedule_monthly_sales_followup_activity(today=today)
            contract.last_sales_followup_period = period
        return True

    @api.model
    def _cron_monthly_sales_followups(self):
        today = fields.Date.context_today(self)
        period = self._sales_followup_period(today)
        contracts = self.search([
            ('active', '=', True),
            ('sales_monthly_reminder_enabled', '=', True),
            ('sales_monthly_reminder_day', '<=', today.day),
            ('state', 'in', ('approved', 'active')),
            '|',
            ('last_sales_followup_period', '=', False),
            ('last_sales_followup_period', '!=', period),
        ])
        raised = 0
        for contract in contracts:
            if contract._schedule_monthly_sales_followup_activity(today=today):
                raised += 1
            contract.with_context(tracking_disable=True).last_sales_followup_period = period
        return raised

    # ------------------------------------------------------------------
    # Approval-lock: block direct edits to commercial fields once the
    # contract is in a locked state. Changes must go through an amendment,
    # which writes with a bypass context flag.
    # ------------------------------------------------------------------
    def write(self, vals):
        if not self.env.context.get('gr_amendment_apply'):
            touched = self._LOCKED_COMMERCIAL_FIELDS & set(vals)
            if touched:
                for c in self:
                    if c.state in self._LOCKED_STATES:
                        raise UserError(_(
                            "Contract %(name)s is %(state)s; its commercial terms are "
                            "locked. Use the Amendment workflow to change %(fields)s.",
                            name=c.name, state=c.state,
                            fields=', '.join(sorted(touched))))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Validation helper for activation/approval
    # ------------------------------------------------------------------
    def _validate_commercial_completeness(self):
        for c in self:
            if c.contract_type == 'hourly' and not c.hourly_rate:
                raise UserError(_(
                    "Contract %s is hourly and requires an hourly rate.") % c.name)
            if c.contract_type in ('daily_with_included_hours',
                                   'monthly_with_included_hours') \
                    and not c.included_hours_per_day:
                raise UserError(_(
                    "Contract %s requires included hours per day.") % c.name)
            # Must have at least one commercial rate set.
            has_rate = any([
                c.base_daily_rate, c.base_monthly_rate, c.hourly_rate,
                c.standby_rate, c.overtime_hour_rate])
            if not has_rate:
                raise UserError(_(
                    "Contract %s has no commercial rates set.") % c.name)

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_submit(self):
        for c in self:
            if c.state != 'draft':
                raise UserError(_("Only draft contracts can be submitted."))
            c.state = 'submitted'
        return True

    def action_approve(self):
        if not (self.env.user.has_group('gr_security_base.group_generator_general_manager')
                or self.env.user.has_group('gr_security_base.group_generator_administrator')):
            raise UserError(_("Only a General Manager or Administrator may approve contracts."))
        for c in self:
            if c.state != 'submitted':
                raise UserError(_("Only submitted contracts can be approved."))
            if not c.site_id:
                raise UserError(_("Contract %s requires a site before approval.") % c.name)
            c._validate_commercial_completeness()
            c.state = 'approved'
            c.message_post(body=_("Contract approved."),
                           message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def action_activate(self):
        for c in self:
            if c.state not in ('approved', 'suspended'):
                raise UserError(_("Only approved or suspended contracts can be activated."))
            if not c.site_id:
                raise UserError(_("Contract %s requires a site before activation.") % c.name)
            c._validate_commercial_completeness()
            c.state = 'active'
        return True

    def action_suspend(self):
        for c in self:
            if c.state != 'active':
                raise UserError(_("Only active contracts can be suspended."))
            c.state = 'suspended'
        return True

    def action_expire(self):
        for c in self:
            if c.state not in ('active', 'suspended'):
                raise UserError(_("Only active or suspended contracts can expire."))
            c.state = 'expired'
        return True

    def action_close(self):
        for c in self:
            if c.state in ('cancelled', 'closed'):
                raise UserError(_("Contract is already closed or cancelled."))
            c.state = 'closed'
        return True

    def action_cancel(self):
        for c in self:
            if c.state in ('closed',):
                raise UserError(_("A closed contract cannot be cancelled."))
            c.state = 'cancelled'
        return True

    def action_reset_to_draft(self):
        for c in self:
            if c.state not in ('cancelled', 'submitted'):
                raise UserError(_("Only cancelled or submitted contracts can return to draft."))
            c.state = 'draft'
        return True

    def action_view_amendments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Amendments'),
            'res_model': 'gr.contract.amendment',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }
