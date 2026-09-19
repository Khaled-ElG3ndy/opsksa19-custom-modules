# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class GrBillingRun(models.Model):
    _name = 'gr.billing.run'
    _description = 'Generator Billing Run'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, string='Currency')

    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Customer (optional filter)',
        help="Restrict this run to one customer. Leave empty to bill all.")
    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order (optional filter)',
        help="Restrict this run to a single rental order.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Generated'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    invoice_ids = fields.Many2many(
        'account.move', string='Generated Invoices', copy=False)
    invoice_count = fields.Integer(
        string='Invoices', compute='_compute_invoice_count')
    log_count = fields.Integer(
        string='Logs Billed', compute='_compute_invoice_count')
    note = fields.Text(string='Note')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The billing-run reference must be unique per company.",
    )

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        Log = self.env['gr.hour.log']
        for run in self:
            run.invoice_count = len(run.invoice_ids)
            run.log_count = Log.search_count([('invoice_id', 'in', run.invoice_ids.ids)])

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.billing.run') or _('New')
        return super().create(vals_list)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for run in self:
            if run.date_from and run.date_to and run.date_to < run.date_from:
                raise UserError(_("'To' date cannot be before 'From' date."))

    # ------------------------------------------------------------------
    def action_set_last_month(self):
        """Convenience: set the range to the previous calendar month."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        first_this = today.replace(day=1)
        last_prev = first_this - relativedelta(days=1)
        self.date_from = last_prev.replace(day=1)
        self.date_to = last_prev
        return True

    # ------------------------------------------------------------------
    def _get_tax(self):
        """Return the 15% KSA sales VAT for this company (created by the module's
        post-init hook; falls back to any matching 15% sale tax)."""
        return self.env['account.tax'].with_company(self.company_id).search([
            ('company_id', '=', self.company_id.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 15.0),
        ], limit=1)

    def _candidate_logs(self):
        """Approved, unbilled logs in range, respecting optional filters."""
        self.ensure_one()
        domain = [
            ('state', '=', 'approved'),
            ('billed', '=', False),
            ('reading_date', '>=', self.date_from),
            ('reading_date', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ]
        if self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))
        if self.rental_order_id:
            domain.append(('rental_order_id', '=', self.rental_order_id.id))
        return self.env['gr.hour.log'].search(domain)

    # ------------------------------------------------------------------
    def action_generate(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only draft billing runs can be generated."))
        logs = self._candidate_logs()
        if not logs:
            raise UserError(_(
                "No approved, unbilled hour logs found in the selected range/"
                "filters."))
        tax = self._get_tax()
        if not tax:
            raise UserError(_(
                "No 15%% KSA sales VAT tax found for company %s. Please create "
                "one or reinstall the billing module.") % self.company_id.name)

        # Group logs per rental order; one draft invoice per order.
        orders = logs.mapped('rental_order_id')
        invoices = self.env['account.move']
        for order in orders:
            order_logs = logs.filtered(lambda l: l.rental_order_id == order)
            move = self._create_invoice_for_order(order, order_logs, tax)
            if move:
                invoices |= move
                order_logs.write({'billed': True, 'invoice_id': move.id})

        if not invoices:
            raise UserError(_("Nothing billable was produced from the logs."))
        self.invoice_ids = [(6, 0, invoices.ids)]
        self.state = 'done'
        orders.invalidate_recordset([
            'invoice_ids', 'invoice_count', 'billable_log_count'])
        self.message_post(
            body=_("Generated %(inv)s draft invoice(s) from %(logs)s approved "
                   "log(s).", inv=len(invoices), logs=len(logs)),
            message_type='comment', subtype_xmlid='mail.mt_note')
        return self.action_view_invoices()

    def _create_invoice_for_order(self, order, order_logs, tax):
        """Build one draft customer invoice for a rental order from its logs."""
        contract = order.contract_id
        partner = order.partner_id
        if not partner:
            return False

        # Aggregate bands across the order's logs in range.
        regular = sum(order_logs.mapped('regular_hours'))
        overtime = sum(order_logs.mapped('overtime_hours'))
        violation = sum(order_logs.mapped('violation_hours'))
        days = sum(order_logs.mapped('days_covered'))

        tax_cmd = [(6, 0, tax.ids)]
        lines = []
        billable_lines = []
        equipment_reference = order._rental_invoice_usage_equipment_reference()

        def line(label, qty, price):
            if qty and price:
                vals = {
                    'name': order._rental_invoice_usage_line_name(label),
                    'quantity': qty,
                    'price_unit': price,
                    'tax_ids': tax_cmd,
                }
                if equipment_reference:
                    vals['rental_equipment_reference'] = equipment_reference
                billable_lines.append((0, 0, vals))

        ctype = contract.contract_type if contract else False
        # Base rental: hourly, daily, or monthly depending on contract type.
        # For monthly contracts, approved hour logs are the billing trigger and
        # usage source, but the base line is a fixed period charge.
        if contract:
            if ctype == 'hourly' and contract.hourly_rate and regular:
                line(_("Hourly Rental"), regular, contract.hourly_rate)
            elif ctype == 'monthly_with_included_hours' and contract.base_monthly_rate:
                line(_("Monthly Rental"), 1.0, contract.base_monthly_rate)
            elif contract.base_daily_rate and days:
                line(_("Base Daily Rental (%s day(s))") % days,
                     days, contract.base_daily_rate)
            # For daily/monthly contracts, regular hours are covered by base
            # rental. Only billable bands beyond included hours are charged.
            if overtime and contract.overtime_hour_rate:
                line(_("Overtime Hours"), overtime, contract.overtime_hour_rate)
            if violation and contract.violation_hour_rate:
                line(_("Violation Hours (over contracted maximum)"),
                     violation, contract.violation_hour_rate)
            if contract.standby_rate:
                # standby billed per day in range if a rate is set
                line(_("Standby"), days or 1, contract.standby_rate)
            # Fuel (only when the company supplies & bills fuel)
            if contract.fuel_billing_policy == 'billed_to_customer' \
                    and contract.fuel_rate:
                fuel_hours = regular + overtime + violation
                line(_("Fuel"), fuel_hours, contract.fuel_rate)

        if not billable_lines:
            return False
        lines.extend(billable_lines)

        move_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'currency_id': self.company_id.currency_id.id,
            'invoice_origin': order.name,
            'rental_order_id': order.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': lines,
            'narration': _("Generated by billing run %(run)s for rental order "
                           "%(order)s covering %(df)s to %(dt)s.",
                           run=self.name, order=order.name,
                           df=self.date_from, dt=self.date_to),
        }
        if contract and contract.analytic_account_id:
            # attach analytic distribution where available (best-effort)
            pass
        move = self.env['account.move'].create(move_vals)
        return move

    # ------------------------------------------------------------------
    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Invoices'),
            'res_model': 'account.move',
            'domain': [('id', 'in', self.invoice_ids.ids)],
            'view_mode': 'list,form',
            'context': {'create': False},
        }

    def action_cancel(self):
        """Release the logs back to billable and cancel the run. Only safe while
        the generated invoices are still in draft."""
        for run in self:
            posted = run.invoice_ids.filtered(lambda m: m.state == 'posted')
            if posted:
                raise UserError(_(
                    "Cannot cancel: invoice(s) %s already posted. Reverse them "
                    "in Accounting first.") % ', '.join(posted.mapped('name')))
            # release logs
            logs = self.env['gr.hour.log'].search([('invoice_id', 'in', run.invoice_ids.ids)])
            orders = logs.mapped('rental_order_id')
            logs.write({'billed': False, 'invoice_id': False})
            # delete the draft invoices
            run.invoice_ids.filtered(lambda m: m.state == 'draft').unlink()
            run.invoice_ids = [(5, 0, 0)]
            run.state = 'cancelled'
            orders.invalidate_recordset([
                'invoice_ids', 'invoice_count', 'billable_log_count'])
        return True
