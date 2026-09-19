# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrMaintenanceContract(models.Model):
    """Recurring paid maintenance contract on a customer-owned generator.
    Auto-generates M7 maintenance jobs (covered), tracks consumable cadence,
    drives a split-payment billing schedule, and separates emergency/T&M work."""
    _name = 'gr.maintenance.contract'
    _description = 'Maintenance Contract (customer-owned)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Contract Ref', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True, index=True)
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Equipment (customer-owned)', required=True,
        index=True, tracking=True,
        domain="[('owner_type', '=', 'customer_owned')]",
        help="The customer-owned generator under this maintenance contract. "
             "Must be flagged Customer-owned (M11) - these units are serviced, "
             "not rented.")

    date_start = fields.Date(string='Start', required=True,
                             default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='End', tracking=True)

    # --- visit schedule ---
    visit_interval_months = fields.Integer(
        string='Visit Every (months)', default=1, required=True,
        help="Periodic-visit cadence. ABSAL's Perkins contract = 1 (monthly).")
    visits_total = fields.Integer(
        string='Total Visits', default=12,
        help="How many covered visits the contract includes. This is suggested "
             "automatically from the start/end dates and visit interval, but "
             "can still be changed manually.")
    maintenance_template_id = fields.Many2one(
        'gr.maintenance.template', string='Visit Template',
        help="Optional M7 template pre-filling each generated visit's checklist.")

    # --- consumable cadence ---
    oil_filter_interval_months = fields.Integer(
        string='Oil + Filters Every (months)', default=6,
        help="Consumable cadence for oil and filters (Perkins contract = 6).")
    battery_once = fields.Boolean(
        string='Battery Once per Contract', default=True,
        help="Battery replacement once over the contract term.")

    # --- pricing / billing schedule ---
    annual_price = fields.Monetary(
        string='Contract Price', currency_field='currency_id', tracking=True,
        help="Total contract value (before VAT). Perkins contract = 9,500 SR.")
    payment_split_count = fields.Integer(
        string='Payments (splits)', default=2,
        help="Number of equal payments across the term (Perkins = 2, i.e. 50% "
             "every 6 months).")
    emergency_visit_rate = fields.Monetary(
        string='Emergency Visit Rate', currency_field='currency_id',
        help="Per-visit charge for out-of-scope emergency / T&M visits "
             "(Perkins contract = 1,500 SR).")
    emergency_response_hours = fields.Integer(
        string='Emergency Response (hours)', default=24,
        help="Committed emergency response window (Perkins = 24h).")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    # --- generated records ---
    visit_ids = fields.One2many(
        'gr.maintenance.job', 'maintenance_contract_id', string='Visits')
    visit_count = fields.Integer(compute='_compute_counts', string='Visits')
    covered_visit_count = fields.Integer(compute='_compute_counts', string='Covered')
    tm_visit_count = fields.Integer(compute='_compute_counts', string='T&M')
    schedule_line_ids = fields.One2many(
        'gr.maintenance.contract.payment', 'contract_id', string='Payment Schedule')
    invoice_count = fields.Integer(compute='_compute_invoice_count', string='Invoices')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The contract reference must be unique per company.",
    )

    def _compute_counts(self):
        for c in self:
            c.visit_count = len(c.visit_ids)
            c.covered_visit_count = len(c.visit_ids.filtered(
                lambda j: j.contract_coverage == 'covered'))
            c.tm_visit_count = len(c.visit_ids.filtered(
                lambda j: j.contract_coverage == 'tm'))

    def _compute_invoice_count(self):
        for c in self:
            c.invoice_count = len(c.schedule_line_ids.mapped('invoice_id'))

    @api.model
    def _suggest_visits_total(self, date_start, date_end, visit_interval_months):
        if not date_start or not date_end or not visit_interval_months:
            return False
        interval = int(visit_interval_months or 0)
        if interval <= 0:
            return False
        start = fields.Date.to_date(date_start)
        end = fields.Date.to_date(date_end)
        if not start or not end:
            return False
        if end <= start:
            return 1

        visits = 0
        visit_date = start
        # Count every generated visit date inside the contract range. The end
        # date is treated as the boundary, so a one-year monthly contract gives
        # 12 visits, not 13.
        while visit_date < end:
            visits += 1
            visit_date += relativedelta(months=interval)
            if visits > 600:
                break
        return max(1, visits)

    def _apply_suggested_visits_total(self):
        for contract in self:
            suggested = contract._suggest_visits_total(
                contract.date_start,
                contract.date_end,
                contract.visit_interval_months,
            )
            if suggested:
                contract.visits_total = suggested

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.maintenance.contract') or _('New')
            if 'visits_total' not in vals:
                suggested = self._suggest_visits_total(
                    vals.get('date_start') or fields.Date.context_today(self),
                    vals.get('date_end'),
                    vals.get('visit_interval_months') or 1,
                )
                if suggested:
                    vals['visits_total'] = suggested
        return super().create(vals_list)

    def write(self, vals):
        if any(field in vals for field in ('date_start', 'date_end', 'visit_interval_months')) \
                and 'visits_total' not in vals:
            for contract in self:
                suggested = contract._suggest_visits_total(
                    vals.get('date_start', contract.date_start),
                    vals.get('date_end', contract.date_end),
                    vals.get('visit_interval_months', contract.visit_interval_months),
                )
                if suggested:
                    contract.with_context(skip_visit_total_suggest=True).write({
                        'visits_total': suggested,
                    })
        return super().write(vals)

    @api.onchange('asset_id')
    def _onchange_asset(self):
        if self.asset_id and self.asset_id.owner_partner_id and not self.partner_id:
            self.partner_id = self.asset_id.owner_partner_id

    @api.onchange('date_start', 'date_end', 'visit_interval_months')
    def _onchange_visit_schedule(self):
        self._apply_suggested_visits_total()

    @api.constrains('visit_interval_months', 'visits_total')
    def _check_positive_visit_schedule(self):
        for contract in self:
            if contract.visit_interval_months <= 0:
                raise ValidationError(_("Visit interval must be positive."))
            if contract.visits_total <= 0:
                raise ValidationError(_("Total visits must be positive."))

    @api.constrains('asset_id')
    def _check_customer_owned(self):
        for c in self:
            if c.asset_id and c.asset_id.owner_type != 'customer_owned':
                raise UserError(_(
                    "Maintenance contract %s: equipment %s must be Customer-owned. "
                    "Rental fleet units are not serviced under customer "
                    "maintenance contracts.") % (c.name, c.asset_id.display_name))

    # ------------------------------------------------------------------
    def action_activate(self):
        for c in self:
            if c.state != 'draft':
                raise UserError(_("Only draft contracts can be activated."))
            if not c.date_end:
                # derive end from the visit plan if not set
                months = max(1, c.visit_interval_months * max(1, c.visits_total))
                c.date_end = c.date_start + relativedelta(months=months)
            c.state = 'active'
            c._generate_visits()
            c._generate_payment_schedule()
        return True

    def action_expire(self):
        self.write({'state': 'expired'})

    def action_cancel(self):
        for c in self:
            if c.state == 'cancelled':
                continue
            c.state = 'cancelled'

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    def _generate_visits(self):
        """Create the covered periodic maintenance visits as M7 jobs."""
        Job = self.env['gr.maintenance.job']
        for c in self:
            existing = len(c.visit_ids.filtered(
                lambda j: j.contract_coverage == 'covered'))
            to_make = max(0, (c.visits_total or 0) - existing)
            months_since_start = existing * c.visit_interval_months
            for i in range(to_make):
                visit_date = c.date_start + relativedelta(
                    months=months_since_start + i * c.visit_interval_months)
                # is oil+filter due on this visit?
                month_offset = (visit_date.year - c.date_start.year) * 12 + \
                               (visit_date.month - c.date_start.month)
                oil_due = (c.oil_filter_interval_months > 0 and
                           month_offset % c.oil_filter_interval_months == 0)
                Job.create({
                    'asset_id': c.asset_id.id,
                    'job_type': 'preventive',
                    'template_id': c.maintenance_template_id.id or False,
                    'scheduled_date': fields.Datetime.to_datetime(visit_date),
                    'maintenance_contract_id': c.id,
                    'contract_coverage': 'covered',
                    'oil_filter_due': oil_due,
                })
        return True

    def _generate_payment_schedule(self):
        """Split the contract price into N equal scheduled payments."""
        Pay = self.env['gr.maintenance.contract.payment']
        for c in self:
            if c.schedule_line_ids:
                continue
            n = max(1, c.payment_split_count)
            term_months = 12
            if c.date_end and c.date_start:
                term_months = max(1, (c.date_end.year - c.date_start.year) * 12 +
                                  (c.date_end.month - c.date_start.month))
            step = max(1, term_months // n)
            amount = (c.annual_price or 0.0) / n
            for i in range(n):
                due = c.date_start + relativedelta(months=i * step)
                Pay.create({
                    'contract_id': c.id,
                    'sequence': (i + 1) * 10,
                    'due_date': due,
                    'amount': amount,
                })
        return True

    def action_log_emergency_visit(self):
        """Create an out-of-scope emergency / T&M visit (billed separately)."""
        self.ensure_one()
        job = self.env['gr.maintenance.job'].create({
            'asset_id': self.asset_id.id,
            'job_type': 'corrective',
            'scheduled_date': fields.Datetime.now(),
            'maintenance_contract_id': self.id,
            'contract_coverage': 'tm',
            'tm_charge': self.emergency_visit_rate,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Emergency / T&M Visit'),
            'res_model': 'gr.maintenance.job',
            'res_id': job.id,
            'view_mode': 'form',
        }

    def action_view_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Visits'),
            'res_model': 'gr.maintenance.job',
            'domain': [('maintenance_contract_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_maintenance_contract_id': self.id,
                        'default_asset_id': self.asset_id.id},
        }


class GrMaintenanceContractPayment(models.Model):
    """A scheduled payment installment for a maintenance contract."""
    _name = 'gr.maintenance.contract.payment'
    _description = 'Maintenance Contract Payment Schedule'
    _order = 'contract_id, sequence, due_date'

    contract_id = fields.Many2one(
        'gr.maintenance.contract', string='Contract', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='contract_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(
        related='contract_id.currency_id', readonly=True)
    sequence = fields.Integer(string='Sequence', default=10)
    due_date = fields.Date(string='Due Date', required=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('invoiced', 'Invoiced'),
    ], string='Status', default='scheduled', required=True)

    def action_create_invoice(self):
        """Generate a draft customer invoice for this installment."""
        Move = self.env['account.move']
        for pay in self:
            if pay.state == 'invoiced':
                raise UserError(_("This installment is already invoiced."))
            c = pay.contract_id
            move = Move.create({
                'move_type': 'out_invoice',
                'partner_id': c.partner_id.id,
                'currency_id': c.currency_id.id,
                'invoice_origin': c.name,
                'company_id': c.company_id.id,
                'invoice_line_ids': [(0, 0, {
                    'name': _("Maintenance contract %(ref)s - installment due %(d)s",
                              ref=c.name, d=pay.due_date),
                    'quantity': 1.0,
                    'price_unit': pay.amount,
                })],
            })
            pay.write({'invoice_id': move.id, 'state': 'invoiced'})
        return True
