# -*- coding: utf-8 -*-
"""Recurring customer rentals.

The company has customers who take roughly the same equipment every month.
Today somebody has to remember who they are, remember what they usually take,
and rebuild the order by hand.

This model remembers the arrangement and reminds the team. It deliberately
stops there: it prepares a DRAFT rental order and nothing more. Confirming,
reserving, dispatching and starting a rental stay manual, because those steps
commit the company to a customer and to a physical unit. Nothing here bypasses
a single rule the rental workflow already enforces - the prepared order goes
through exactly the same validations as one typed by hand.
"""
import calendar
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date


class GrRecurringRental(models.Model):
    _name = 'gr.recurring.rental'
    _description = 'Recurring Customer Rental'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'next_rental_date, name'

    # Contract states in which an order may legitimately be prepared. Mirrors
    # gr.rental.order.action_confirm so we never prepare something the rental
    # workflow would refuse to confirm.
    _VALID_CONTRACT_STATES = ('approved', 'active')
    # Order states in which a previously prepared order still "counts", so the
    # occurrence is not re-prepared behind the user's back.
    _LIVE_ORDER_STATES_EXCLUDED = ('cancelled',)

    name = fields.Char(
        string='Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    active = fields.Boolean(
        default=True, tracking=True,
        help="Archive to pause the arrangement. A paused arrangement raises no "
             "reminders and prepares no orders, but keeps its full history and "
             "can be reactivated at any time.")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, index=True,
        tracking=True)
    site_id = fields.Many2one(
        'gr.customer.site', string='Site', tracking=True,
        domain="[('partner_id', '=', partner_id)]",
        help="A customer may have one arrangement per site, each on its own "
             "schedule.")
    contract_id = fields.Many2one(
        'gr.rental.contract', string='Rental Contract', tracking=True,
        domain="[('partner_id', '=', partner_id)]",
        help="The contract the prepared orders are booked against. Its rates "
             "are what the order is priced on, so it must be approved or "
             "active before an order can be prepared.")
    contract_state = fields.Selection(
        related='contract_id.state', string='Contract Status', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Responsible', required=True, tracking=True,
        default=lambda self: self.env.user,
        help="Who gets the reminder activity and prepares the order.")

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    frequency = fields.Selection([
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ], string='Frequency', default='monthly', required=True, tracking=True)
    interval = fields.Integer(
        string='Repeat Every', default=1, required=True, tracking=True,
        help="Number of weeks or months between rentals. 1 = every month, "
             "2 = every second month.")
    day_of_month = fields.Integer(
        string='Day of Month', tracking=True,
        help="The day the rental normally starts, 1-31. A month that is too "
             "short uses its last day (31 becomes 28 or 29 in February) and "
             "the following month returns to the configured day.")
    next_rental_date = fields.Date(
        string='Next Rental Date', required=True, tracking=True, index=True,
        default=fields.Date.context_today,
        help="The occurrence currently due. It only moves when the occurrence "
             "is explicitly prepared or skipped - never on its own.")
    reminder_days_before = fields.Integer(
        string='Remind Days Before', default=2, required=True, tracking=True,
        help="Lead time for this customer specifically. Set per arrangement: "
             "one customer may want two days' notice, another five.")
    next_reminder_date = fields.Date(
        string='Next Reminder Date', compute='_compute_next_reminder_date',
        store=True, index=True)
    rental_duration_days = fields.Integer(
        string='Rental Duration (days)', default=30, required=True,
        help="Used to derive the prepared order's Planned Return from its "
             "Planned Dispatch.")
    planned_return_preview = fields.Date(
        string='Expected Return', compute='_compute_planned_return_preview')

    occurrence_state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('due_soon', 'Reminder Due'),
        ('due_today', 'Due Today'),
        ('overdue', 'Overdue'),
    ], string='Status', compute='_compute_occurrence_state', store=True,
        index=True, default='scheduled',
        help="Where the current occurrence stands against today's date. An "
             "occurrence that passes unhandled stays Overdue until somebody "
             "prepares or skips it; it is never advanced silently.")

    line_ids = fields.One2many(
        'gr.recurring.rental.line', 'recurring_id', string='Recurring Items',
        copy=True)
    occurrence_ids = fields.One2many(
        'gr.recurring.rental.occurrence', 'recurring_id',
        string='Occurrence History', readonly=True)
    order_ids = fields.One2many(
        'gr.rental.order', 'recurring_rental_id', string='Prepared Orders',
        readonly=True)
    order_count = fields.Integer(
        string='Prepared Orders', compute='_compute_order_count')
    last_order_id = fields.Many2one(
        'gr.rental.order', string='Last Prepared Order', readonly=True,
        copy=False)
    last_prepared_date = fields.Date(
        string='Last Prepared On', readonly=True, copy=False)
    notes = fields.Text(string='Notes')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The recurring rental reference must be unique per company.",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('next_rental_date', 'reminder_days_before')
    def _compute_next_reminder_date(self):
        for rec in self:
            rec.next_reminder_date = (
                rec.next_rental_date
                - relativedelta(days=max(0, rec.reminder_days_before or 0))
                if rec.next_rental_date else False)

    @api.depends('next_rental_date', 'rental_duration_days')
    def _compute_planned_return_preview(self):
        for rec in self:
            rec.planned_return_preview = (
                rec.next_rental_date
                + relativedelta(days=max(0, rec.rental_duration_days or 0))
                if rec.next_rental_date else False)

    @api.depends('next_rental_date', 'next_reminder_date', 'active')
    def _compute_occurrence_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.next_rental_date:
                rec.occurrence_state = 'scheduled'
            elif rec.next_rental_date < today:
                rec.occurrence_state = 'overdue'
            elif rec.next_rental_date == today:
                rec.occurrence_state = 'due_today'
            elif rec.next_reminder_date and rec.next_reminder_date <= today:
                rec.occurrence_state = 'due_soon'
            else:
                rec.occurrence_state = 'scheduled'

    def _compute_order_count(self):
        counts = dict.fromkeys(self.ids, 0)
        for rec, count in self.env['gr.rental.order']._read_group(
                [('recurring_rental_id', 'in', self.ids)],
                ['recurring_rental_id'], ['__count']):
            counts[rec.id] = count
        for rec in self:
            rec.order_count = counts.get(rec.id, 0)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('interval')
    def _check_interval(self):
        for rec in self:
            if rec.interval < 1:
                raise ValidationError(_(
                    "Repeat Every must be at least 1 for %s.") % rec.display_name)

    @api.constrains('reminder_days_before')
    def _check_reminder_days(self):
        for rec in self:
            if rec.reminder_days_before < 0:
                raise ValidationError(_(
                    "Remind Days Before cannot be negative for %s.")
                    % rec.display_name)

    @api.constrains('rental_duration_days')
    def _check_duration(self):
        for rec in self:
            if rec.rental_duration_days < 1:
                raise ValidationError(_(
                    "Rental Duration must be at least one day for %s.")
                    % rec.display_name)

    @api.constrains('day_of_month')
    def _check_day_of_month(self):
        for rec in self:
            if rec.day_of_month and not (1 <= rec.day_of_month <= 31):
                raise ValidationError(_(
                    "Day of Month must be between 1 and 31 for %s.")
                    % rec.display_name)

    @api.constrains('site_id', 'partner_id')
    def _check_site_partner(self):
        for rec in self:
            if rec.site_id and rec.site_id.partner_id != rec.partner_id:
                raise ValidationError(_(
                    "Site %(site)s does not belong to customer %(partner)s.",
                    site=rec.site_id.display_name,
                    partner=rec.partner_id.display_name))

    @api.constrains('contract_id', 'partner_id')
    def _check_contract_partner(self):
        for rec in self:
            if rec.contract_id and rec.contract_id.partner_id != rec.partner_id:
                raise ValidationError(_(
                    "Contract %(contract)s does not belong to customer "
                    "%(partner)s.",
                    contract=rec.contract_id.display_name,
                    partner=rec.partner_id.display_name))

    # ------------------------------------------------------------------
    # Onchanges
    # ------------------------------------------------------------------
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.site_id and self.site_id.partner_id != self.partner_id:
            self.site_id = False
        if self.contract_id and self.contract_id.partner_id != self.partner_id:
            self.contract_id = False

    @api.onchange('next_rental_date', 'frequency')
    def _onchange_next_rental_date(self):
        # The anchor day follows the date the user typed, so a monthly
        # arrangement "just works" without them finding a second field.
        if self.frequency == 'monthly' and self.next_rental_date:
            self.day_of_month = self.next_rental_date.day

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.recurring.rental') or _('New')
            if not vals.get('day_of_month') and vals.get('next_rental_date'):
                start = fields.Date.to_date(vals['next_rental_date'])
                vals['day_of_month'] = start.day
        records = super().create(vals_list)
        for rec in records:
            rec.message_post(body=_(
                "Recurring rental created. First occurrence: %(date)s, "
                "reminder %(days)s day(s) before.",
                date=format_date(self.env, rec.next_rental_date),
                days=rec.reminder_days_before))
        return records

    def write(self, vals):
        # A changed occurrence date is the one thing nobody should discover by
        # accident, so it is always narrated in the chatter.
        narrate = 'next_rental_date' in vals and not self.env.context.get(
            'gr_recurring_internal_write')
        before = {rec.id: rec.next_rental_date for rec in self} if narrate else {}
        res = super().write(vals)
        if narrate:
            for rec in self:
                old = before.get(rec.id)
                if old != rec.next_rental_date:
                    rec.message_post(body=_(
                        "Next rental date changed from %(old)s to %(new)s.",
                        old=format_date(self.env, old) if old else _("not set"),
                        new=format_date(self.env, rec.next_rental_date)))
        return res

    # ------------------------------------------------------------------
    # Schedule arithmetic
    # ------------------------------------------------------------------
    def _next_occurrence_date(self, from_date):
        """The occurrence after `from_date`, honouring the anchor day.

        Month arithmetic is done from the anchor rather than from the previous
        result, so a 31st arrangement that lands on 28 February returns to the
        31st in March instead of drifting down the calendar for good.
        """
        self.ensure_one()
        interval = max(1, self.interval or 1)
        if self.frequency == 'weekly':
            return from_date + relativedelta(weeks=interval)
        shifted = from_date + relativedelta(months=interval)
        anchor = self.day_of_month or from_date.day
        last_day = calendar.monthrange(shifted.year, shifted.month)[1]
        return date(shifted.year, shifted.month, min(anchor, last_day))

    def _advance_occurrence(self):
        for rec in self:
            rec.with_context(gr_recurring_internal_write=True).next_rental_date = \
                rec._next_occurrence_date(rec.next_rental_date)

    # ------------------------------------------------------------------
    # Reminder activities
    # ------------------------------------------------------------------
    def _reminder_summary(self):
        self.ensure_one()
        return _("Prepare recurring rental")

    def _reminder_note(self):
        self.ensure_one()
        return _(
            "It is time to prepare the recurring rental for %(customer)s. "
            "Next rental date: %(date)s.",
            customer=self.partner_id.display_name,
            date=format_date(self.env, self.next_rental_date))

    def _existing_reminder_activities(self, occurrence_date=None):
        """Open reminder activities for this arrangement's occurrence."""
        self.ensure_one()
        domain = [
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('summary', '=', self._reminder_summary()),
        ]
        if occurrence_date:
            domain.append(('date_deadline', '=', occurrence_date))
        return self.env['mail.activity'].search(domain)

    def _schedule_reminder_activity(self):
        """One open activity per occurrence, whatever the cron does.

        Identity is (record, summary, deadline=occurrence date). Re-running the
        cron on the same day, or on any later day while the occurrence is still
        unhandled, finds that activity and leaves it alone.
        """
        self.ensure_one()
        if self._existing_reminder_activities(self.next_rental_date):
            return False
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=self._reminder_summary(),
            note=self._reminder_note(),
            date_deadline=self.next_rental_date,
            user_id=self.user_id.id or self.env.user.id,
        )
        self.message_post(body=_(
            "Reminder raised for %(user)s: rental due %(date)s.",
            user=self.user_id.display_name,
            date=format_date(self.env, self.next_rental_date)))
        return True

    def _close_reminder_activities(self, occurrence_date, feedback):
        """Never leave an activity telling somebody to do what is already done."""
        self.ensure_one()
        activities = self._existing_reminder_activities(occurrence_date)
        if activities:
            activities.action_feedback(feedback=feedback)
        return bool(activities)

    @api.model
    def _cron_recurring_rental_reminders(self):
        """Daily: raise reminders that have come due. Nothing else.

        This never prepares an order and never moves a date. Its whole job is
        to make sure a human is told. Overdue arrangements keep their reminder
        and stay visible rather than rolling quietly forward.
        """
        today = fields.Date.context_today(self)
        due = self.search([
            ('active', '=', True),
            ('next_rental_date', '!=', False),
            ('next_reminder_date', '<=', today),
        ])
        raised = 0
        for rec in due:
            # An occurrence already prepared or skipped needs no nagging, even
            # if its date has not been advanced for some reason.
            if rec._occurrence_record(rec.next_rental_date):
                continue
            if rec._schedule_reminder_activity():
                raised += 1
        # The status column is relative to today, so refresh the stored value
        # for everything still open rather than only for what got a reminder.
        stale = self.search([('next_rental_date', '!=', False)])
        if stale:
            self.env.add_to_compute(self._fields['occurrence_state'], stale)
            stale.flush_recordset(['occurrence_state'])
        return raised

    # ------------------------------------------------------------------
    # Occurrence bookkeeping
    # ------------------------------------------------------------------
    def _occurrence_record(self, occurrence_date):
        """The handled-occurrence log entry for a date, if any.

        A prepared occurrence whose order was cancelled no longer counts: the
        arrangement is free to prepare a replacement rather than being stuck.
        """
        self.ensure_one()
        occurrence = self.env['gr.recurring.rental.occurrence'].search([
            ('recurring_id', '=', self.id),
            ('occurrence_date', '=', occurrence_date),
        ], limit=1)
        if not occurrence:
            return occurrence
        if occurrence.state == 'prepared':
            order = occurrence.order_id
            if not order.exists() or order.state in self._LIVE_ORDER_STATES_EXCLUDED:
                return self.env['gr.recurring.rental.occurrence']
        return occurrence

    def _record_occurrence(self, occurrence_date, state, order=None, note=False):
        self.ensure_one()
        Occurrence = self.env['gr.recurring.rental.occurrence']
        existing = Occurrence.search([
            ('recurring_id', '=', self.id),
            ('occurrence_date', '=', occurrence_date),
        ], limit=1)
        vals = {
            'recurring_id': self.id,
            'occurrence_date': occurrence_date,
            'state': state,
            'order_id': order.id if order else False,
            'note': note,
        }
        if existing:
            existing.write(vals)
            return existing
        return Occurrence.create(vals)

    # ------------------------------------------------------------------
    # Preparation checks
    # ------------------------------------------------------------------
    def _check_ready_to_prepare(self):
        self.ensure_one()
        if not self.active:
            raise UserError(_(
                "%s is paused. Reactivate it before preparing an order.")
                % self.display_name)
        if not self.next_rental_date:
            raise UserError(_(
                "%s has no next rental date.") % self.display_name)
        if not self.line_ids:
            raise UserError(_(
                "%s has no recurring items. Add what the customer normally "
                "rents before preparing an order.") % self.display_name)
        # Contract validity, using the same states the rental order demands at
        # confirmation. Preparing an order that could never be confirmed only
        # wastes the operator's time.
        if not self.contract_id:
            raise UserError(_(
                "%s has no rental contract. A rental order cannot be confirmed "
                "without one.") % self.display_name)
        if self.contract_id.state not in self._VALID_CONTRACT_STATES:
            raise UserError(_(
                "The rental contract linked to this recurring rental is not "
                "active. Review the contract before preparing the order.\n\n"
                "Contract: %(contract)s\nStatus: %(state)s",
                contract=self.contract_id.display_name,
                state=dict(self.contract_id._fields['state']._description_selection(
                    self.env)).get(self.contract_id.state, self.contract_id.state)))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_prepare_next_rental(self):
        """Create THIS occurrence's rental order, as a draft, and open it.

        Everything the arrangement knows is copied in; nothing is committed.
        The order is not confirmed, no asset is reserved, no approval document
        is generated. A unit that cannot be safely pre-filled is left off the
        line for the operator to choose.
        """
        self.ensure_one()
        self._check_ready_to_prepare()
        occurrence_date = self.next_rental_date

        handled = self._occurrence_record(occurrence_date)
        if handled:
            if handled.state == 'skipped':
                raise UserError(_(
                    "The %s occurrence was skipped. Move to the next date or "
                    "change the next rental date to prepare an order.")
                    % format_date(self.env, occurrence_date))
            raise UserError(_(
                "The rental order for the %(date)s occurrence has already been "
                "prepared (%(order)s).",
                date=format_date(self.env, occurrence_date),
                order=handled.order_id.display_name))

        start = occurrence_date
        end = start + relativedelta(days=max(1, self.rental_duration_days or 1))
        order = self.env['gr.rental.order'].with_context(
            gr_skip_primary_asset_sync=True,
        ).create(self._prepare_order_vals(start, end))

        unresolved = self._create_order_lines(order, start, end)
        if unresolved:
            order.message_post(body=_(
                "Prepared from recurring rental %(ref)s. The following items "
                "still need a physical unit selected before the order can be "
                "reserved:<br/>%(items)s",
                ref=self.display_name,
                items='<br/>'.join('- %s' % reason for reason in unresolved)))
        else:
            order.message_post(body=_(
                "Prepared from recurring rental %s.") % self.display_name)

        self._record_occurrence(occurrence_date, 'prepared', order=order)
        self.write({
            'last_order_id': order.id,
            'last_prepared_date': fields.Date.context_today(self),
        })
        self._close_reminder_activities(
            occurrence_date, _("Rental order %s prepared.") % order.name)
        self._advance_occurrence()
        self.message_post(body=_(
            "Rental order %(order)s prepared for %(date)s. Next occurrence: "
            "%(next)s.",
            order=order.name,
            date=format_date(self.env, occurrence_date),
            next=format_date(self.env, self.next_rental_date)))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Draft Rental Order'),
            'res_model': 'gr.rental.order',
            'res_id': order.id,
            'view_mode': 'form',
        }

    def action_skip_occurrence(self):
        self.ensure_one()
        if not self.next_rental_date:
            raise UserError(_("%s has no next rental date.") % self.display_name)
        skipped = self.next_rental_date
        if self._occurrence_record(skipped):
            raise UserError(_(
                "The %s occurrence has already been handled.")
                % format_date(self.env, skipped))
        self._record_occurrence(skipped, 'skipped')
        self._close_reminder_activities(
            skipped, _("Occurrence skipped."))
        self._advance_occurrence()
        self.message_post(body=_(
            "The recurring rental occurrence of %(date)s was skipped. Next "
            "occurrence: %(next)s.",
            date=format_date(self.env, skipped),
            next=format_date(self.env, self.next_rental_date)))
        return True

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rental Orders'),
            'res_model': 'gr.rental.order',
            'domain': [('recurring_rental_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_recurring_rental_id': self.id},
        }

    def toggle_active(self):
        res = super().toggle_active()
        for rec in self:
            rec.message_post(body=(
                _("Recurring rental reactivated.") if rec.active
                else _("Recurring rental paused. No reminders will be raised.")))
        return res

    # ------------------------------------------------------------------
    # Order building
    # ------------------------------------------------------------------
    def _prepare_order_vals(self, start, end):
        self.ensure_one()
        start_dt = fields.Datetime.to_datetime(start)
        return {
            'partner_id': self.partner_id.id,
            'site_id': self.site_id.id,
            'contract_id': self.contract_id.id,
            'company_id': self.company_id.id,
            'recurring_rental_id': self.id,
            'date_requested': start_dt,
            'planned_dispatch_datetime': start_dt,
            'planned_return_datetime': fields.Datetime.to_datetime(end),
        }

    def _create_order_lines(self, order, start, end):
        """Expand the template onto the order. Returns unresolved-unit notes.

        Quantity becomes one line per physical unit, because that is how the
        rental order already models things: each line is one serial that can be
        tracked and not double-booked.
        """
        self.ensure_one()
        Line = self.env['gr.rental.order.line']
        duration_days = max(1, (end - start).days)
        unresolved = []
        sequence = 10
        for template in self.line_ids.sorted('sequence'):
            asset, reason = template._resolve_preferred_asset(start, end)
            for index in range(max(1, template.quantity)):
                vals = template._order_line_vals(duration_days)
                vals.update({'order_id': order.id, 'sequence': sequence})
                # Only the first unit of a quantity inherits the preferred
                # asset: one physical serial cannot be in two lines.
                if asset and index == 0:
                    vals['equipment_asset_id'] = asset.id
                Line.create(vals)
                sequence += 10
            if reason:
                unresolved.append(reason)
            elif asset and template.quantity > 1:
                unresolved.append(_(
                    "%(item)s: %(count)s more unit(s) still need a serial.",
                    item=template.display_name, count=template.quantity - 1))
        return unresolved
