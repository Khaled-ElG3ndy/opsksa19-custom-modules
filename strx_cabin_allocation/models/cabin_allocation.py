# -*- coding: utf-8 -*-
import logging
import math
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

# Allocation states that still hold a serial (used by the overlap check).
# Once an allocation is Returned, the commercial rental is closed and the serial
# can be reused for a new rental.
ACTIVE_STATES = ('draft', 'allocated', 'dispatched', 'on_rent')


class StrxCabinAllocation(models.Model):
    """The exact serial committed to a rental order line.

    Logistics is free to pick ANY eligible unit of the CORRECT specification, but
    never a different specification (enforced by _check_spec_match), and the same
    serial can never back two overlapping rentals (enforced by _check_no_overlap).
    This record is the source of truth the dispatch hard-stop will validate against.
    """
    _name = 'strx.cabin.allocation'
    _description = 'Cabin Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True, index=True,
        default=lambda self: _('New'))

    order_line_id = fields.Many2one(
        'sale.order.line', string='Rental Line', required=True, ondelete='cascade',
        index=True, tracking=True)
    order_id = fields.Many2one(
        'sale.order', string='Rental Order', related='order_line_id.order_id',
        store=True, index=True, readonly=True)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', related='order_id.partner_id',
        store=True, readonly=True)

    # Committed specification: a SNAPSHOT of the line's product, not a live related
    # field — so a later line change cannot silently mutate the commitment.
    product_id = fields.Many2one(
        'product.product', string='Required Specification', required=True,
        readonly=True, index=True, tracking=True)
    product_tmpl_id = fields.Many2one(
        'product.template', related='product_id.product_tmpl_id', readonly=True)
    strx_cabin_spec = fields.Char(
        related='product_id.strx_cabin_spec', string='Specification', readonly=True)

    # Three-tier selection list (client requirement):
    #   damaged / retired          -> hidden entirely (absent from this domain)
    #   on rent / in maintenance   -> VISIBLE, colour-coded and labelled, NOT committable
    #   available                  -> selectable
    # The picker only makes tier 2 visible; refusing to COMMIT it is enforced
    # server-side in _strx_assert_lot_selectable below, never by this domain.
    # ``lot_id`` is retained as a hidden compatibility pointer for integrations that
    # pre-date multi-unit sale lines.  New code and the UI use ``lot_ids``; the write
    # bridge below always keeps this field equal to the first selected serial.
    lot_id = fields.Many2one(
        'stock.lot', string='Legacy Allocated Serial', index=True,
        domain="['&', '&', ('product_id', '=', product_id),"
               " ('strx_hidden_from_selection', '=', False),"
               " '|', ('strx_selectable', '=', True),"
               " ('strx_readiness_state', 'in', ['on_rent', 'in_maintenance'])]",
        context={
            'strx_selection_label': 1,
            'list_view_ref': 'strx_cabin_allocation.view_lot_picker_strx',
        },
        help="Compatibility pointer to the first allocated serial.")
    lot_ids = fields.Many2many(
        'stock.lot', 'strx_cabin_allocation_stock_lot_rel',
        'allocation_id', 'lot_id', string='Allocated Serials', tracking=True,
        domain="['&', '&', ('product_id', '=', product_id),"
               " ('strx_hidden_from_selection', '=', False),"
               " '|', ('strx_selectable', '=', True),"
               " ('strx_readiness_state', 'in', ['on_rent', 'in_maintenance'])]",
        context={
            'strx_selection_label': 1,
            'list_view_ref': 'strx_cabin_allocation.view_lot_picker_strx',
        },
        help="Exact physical units committed. Their count must match the rental-line "
             "quantity and every unit must be Available at allocation time. Units on "
             "rent or in maintenance are shown for planning visibility but cannot be "
             "committed.")
    required_serial_count = fields.Integer(
        string='Required Serials', compute='_compute_serial_counts')
    selected_serial_count = fields.Integer(
        string='Selected Serials', compute='_compute_serial_counts')
    serial_selection_status = fields.Char(
        string='Serial Selection', compute='_compute_serial_counts')

    strx_date_out = fields.Date(string='Planned Dispatch', tracking=True)
    strx_expected_return_date = fields.Date(string='Expected Return', tracking=True)
    strx_actual_return_date = fields.Date(string='Actual Return')
    strx_rental_days = fields.Integer(
        string='Rental Days', compute='_compute_strx_rental_days', store=True)
    strx_return_alert_activity_ids = fields.Many2many(
        'mail.activity',
        compute='_compute_strx_return_alert_activity_ids',
        string='Return Alert Activities')
    strx_return_alert_count = fields.Integer(
        string='Return Alerts',
        compute='_compute_strx_return_alert_activity_ids')
    strx_return_timing_label = fields.Char(
        string='Return Timing',
        compute='_compute_strx_return_timing')
    strx_return_timing_level = fields.Selection(
        selection=[
            ('none', 'No Date'),
            ('normal', 'On Track'),
            ('today', 'Due Today'),
            ('overdue', 'Overdue'),
        ],
        string='Return Timing Status',
        compute='_compute_strx_return_timing')
    strx_return_alert_two_days_sent = fields.Boolean(
        string='Two-Business-Day Return Alert Sent', copy=False)
    strx_return_alert_today_sent = fields.Boolean(
        string='Today Return Alert Sent', copy=False)
    strx_return_alert_overdue_sent = fields.Boolean(
        string='Overdue Return Alert Sent', copy=False)

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('allocated', 'Allocated'),
            ('dispatched', 'Dispatched'),
            ('on_rent', 'On Rent'),
            ('returned', 'Returned'),
            # Kept as the technical key for upgrade compatibility.  The allocation
            # is assessed/closed here; each lot carries its own real readiness.
            ('available', 'Assessed'),
            ('done', 'Done'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, copy=False, tracking=True)

    strx_lot_readiness_state = fields.Selection(
        selection=lambda self: self.env['stock.lot']._fields[
            'strx_readiness_state']._description_selection(self.env),
        compute='_compute_lot_readiness', string='Cabin Readiness', readonly=True)
    strx_all_lots_available = fields.Boolean(compute='_compute_lot_readiness')

    company_id = fields.Many2one(
        'res.company', related='order_id.company_id', store=True, readonly=True)

    def init(self):
        """Backfill the multi-serial relation without losing existing allocations."""
        self.env.cr.execute("""
            INSERT INTO strx_cabin_allocation_stock_lot_rel (allocation_id, lot_id)
            SELECT allocation.id, allocation.lot_id
              FROM strx_cabin_allocation allocation
             WHERE allocation.lot_id IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM strx_cabin_allocation_stock_lot_rel relation
                     WHERE relation.allocation_id = allocation.id
                       AND relation.lot_id = allocation.lot_id
               )
        """)

    # ------------------------------------------------------------------ compute
    @api.depends('strx_date_out', 'strx_expected_return_date')
    def _compute_strx_rental_days(self):
        for alloc in self:
            if alloc.strx_date_out and alloc.strx_expected_return_date:
                alloc.strx_rental_days = (
                    alloc.strx_expected_return_date - alloc.strx_date_out).days
            else:
                alloc.strx_rental_days = 0

    @api.depends('order_line_id.product_uom_qty', 'lot_ids')
    @api.depends_context('lang')
    def _compute_serial_counts(self):
        for alloc in self:
            required = max(int(math.ceil(
                alloc.order_line_id.product_uom_qty or 0.0)), 0)
            selected = len(alloc.lot_ids)
            alloc.required_serial_count = required
            alloc.selected_serial_count = selected
            alloc.serial_selection_status = _(
                "Selected %(selected)s of %(required)s serials",
                selected=selected, required=required)

    @api.depends('lot_ids.strx_readiness_state')
    def _compute_lot_readiness(self):
        for alloc in self:
            states = set(alloc.lot_ids.mapped('strx_readiness_state'))
            alloc.strx_lot_readiness_state = states.pop() if len(states) == 1 else False
            alloc.strx_all_lots_available = bool(alloc.lot_ids) and all(
                lot.strx_readiness_state == 'available' for lot in alloc.lot_ids)

    def _compute_strx_return_alert_activity_ids(self):
        activity_type = self.env.ref('mail.mail_activity_data_todo',
                                     raise_if_not_found=False)
        if not activity_type:
            for alloc in self:
                alloc.strx_return_alert_activity_ids = False
                alloc.strx_return_alert_count = 0
            return
        for alloc in self:
            target = alloc._strx_return_alert_target_record()
            model = self.env['ir.model']._get(target._name)
            activities = self.env['mail.activity'].search([
                ('res_model_id', '=', model.id),
                ('res_id', '=', target.id),
                ('activity_type_id', '=', activity_type.id),
                ('summary', 'in', alloc._strx_return_alert_summaries()),
            ])
            alloc.strx_return_alert_activity_ids = activities
            alloc.strx_return_alert_count = len(activities)

    @api.depends('state', 'strx_expected_return_date')
    @api.depends_context('lang')
    def _compute_strx_return_timing(self):
        today = fields.Date.context_today(self)
        for alloc in self:
            if alloc.state != 'on_rent':
                alloc.strx_return_timing_label = False
                alloc.strx_return_timing_level = 'none'
                continue
            if not alloc.strx_expected_return_date:
                alloc.strx_return_timing_label = _('No return date')
                alloc.strx_return_timing_level = 'none'
                continue
            remaining_days = (alloc.strx_expected_return_date - today).days
            if remaining_days < 0:
                alloc.strx_return_timing_label = _(
                    'Overdue by %(days)s days', days=abs(remaining_days))
                alloc.strx_return_timing_level = 'overdue'
            elif remaining_days == 0:
                alloc.strx_return_timing_label = _('Due today')
                alloc.strx_return_timing_level = 'today'
            else:
                alloc.strx_return_timing_label = _(
                    '%(days)s days remaining', days=remaining_days)
                alloc.strx_return_timing_level = 'normal'

    # ----------------------------------------------------------------- onchange
    @api.onchange('order_line_id')
    def _onchange_order_line_id(self):
        """Snapshot the committed product from the chosen rental line."""
        if self.order_line_id:
            self.product_id = self.order_line_id.product_id
            self._strx_apply_line_rental_period()
            # Reset a now-mismatched serial.
            mismatched = self.lot_ids.filtered(
                lambda lot: lot.product_id != self.product_id)
            if mismatched:
                self.lot_ids -= mismatched

    def _strx_apply_line_rental_period(self):
        self.ensure_one()
        line = self.order_line_id
        if not line:
            return
        if line.strx_rental_start_date:
            self.strx_date_out = line.strx_rental_start_date
        if line.strx_expected_return_date:
            self.strx_expected_return_date = line.strx_expected_return_date

    @api.onchange('lot_ids')
    def _onchange_lot_ids(self):
        """Reject unavailable/extra values and warn while selection is incomplete."""
        unavailable = self.lot_ids.filtered(lambda lot: not lot.strx_selectable)
        if unavailable:
            serial = unavailable[0].name
            state = unavailable[0].strx_state_label \
                or unavailable[0].strx_readiness_state
            self.lot_ids -= unavailable
            return {
                'warning': {
                    'title': _("Serial not available"),
                    'message': _(
                        "Serial %(serial)s is %(state)s and cannot be selected.",
                        serial=serial,
                        state=state),
                }
            }
        required = self.required_serial_count
        if required and len(self.lot_ids) > required:
            previous = self._origin.lot_ids if self._origin else self.env['stock.lot']
            keep = previous & self.lot_ids
            remaining = self.lot_ids - keep
            allowed = (keep | remaining[:max(required - len(keep), 0)])[:required]
            self.lot_ids = allowed
            return {'warning': {
                'title': _("Too many serials"),
                'message': _(
                    "This rental line requires %(required)s serials. You cannot "
                    "select more than the ordered quantity.", required=required),
            }}

        if required and len(self.lot_ids) < required:
            return {'warning': {
                'title': _("Serial selection incomplete"),
                'message': _(
                    "Selected %(selected)s of %(required)s serials. Select "
                    "%(remaining)s more before allocating.",
                    selected=len(self.lot_ids), required=required,
                    remaining=required - len(self.lot_ids)),
            }}

    @api.onchange('lot_id')
    def _onchange_lot_id(self):
        """Compatibility path for old RPC clients that still send one serial."""
        self.lot_ids = self.lot_id
        result = self._onchange_lot_ids()
        self.lot_id = self.lot_ids[:1]
        return result

    # ------------------------------------------------- commitment eligibility
    def _strx_assert_lot_selectable(self, lot):
        """A serial may only be COMMITTED while it is genuinely Available.

        Tier 2 (on rent / in maintenance) is visible in the picker so a planner can
        see the unit exists and why it is not free — never so it can be committed.
        The refusal lives here, at the model, so an import, an RPC call or a forced
        write is rejected exactly like a pick from the dropdown. A greyed row is a
        courtesy; this is the control.

        TODO (Phase 2) forward booking: reserving a unit that is on rent now for a
        period starting after it returns is a legitimate need, but it carries its own
        edge cases — rental extension, damage on return, re-allocation of the
        returning unit. It is deliberately NOT opened here. When it is built, it
        belongs on the existing date-range overlap foundation (_check_no_overlap),
        gating on the PERIOD rather than on the unit's state right now.
        """
        if not lot:
            return
        invalid = lot.filtered(lambda serial: not serial.strx_selectable)
        if not invalid:
            return
        lot = invalid[0]
        labels = dict(
            lot._fields['strx_readiness_state']._description_selection(self.env))
        raise ValidationError(_(
            "Cabin %(serial)s cannot be allocated — it is %(state)s, not Available.\n"
            "It is shown in the list for planning visibility only. Choose an "
            "available unit of the same specification, or raise a substitution "
            "request.",
            serial=lot.name,
            state=labels.get(lot.strx_readiness_state, lot.strx_readiness_state)))

    # ----------------------------------------------------------------- create
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'strx.cabin.allocation') or _('New')
            # Snapshot product from the line if not explicitly provided.
            if not vals.get('product_id') and vals.get('order_line_id'):
                line = self.env['sale.order.line'].browse(vals['order_line_id'])
                vals['product_id'] = line.product_id.id
            if vals.get('order_line_id'):
                line = self.env['sale.order.line'].browse(vals['order_line_id'])
                vals.setdefault('strx_date_out', line.strx_rental_start_date)
                vals.setdefault(
                    'strx_expected_return_date',
                    line.strx_expected_return_date)
            if vals.get('lot_id') and not vals.get('lot_ids'):
                vals['lot_ids'] = [(6, 0, [vals['lot_id']])]
        allocs = super().create(vals_list)
        for alloc in allocs:
            alloc._strx_assert_lot_selectable(alloc.lot_ids)
        allocs._strx_sync_legacy_lot_id()
        allocs._strx_schedule_due_return_alerts_now()
        return allocs

    # ------------------------------------------------------------------ write
    def write(self, vals):
        if self.env.context.get('strx_sync_legacy_lot_id'):
            return super().write(vals)
        vals = dict(vals)
        if 'lot_id' in vals and 'lot_ids' not in vals:
            vals['lot_ids'] = [(6, 0, [vals['lot_id']])] if vals['lot_id'] else [(5, 0, 0)]
        old_lots_by_alloc = {alloc.id: alloc.lot_ids for alloc in self}
        allocated_serial_changes = {}
        if 'lot_ids' in vals and not self.env.context.get(
                'strx_skip_allocated_serial_change_alert'):
            for alloc in self:
                if alloc.state == 'allocated':
                    allocated_serial_changes[alloc.id] = alloc.lot_ids
        reset_alerts = 'strx_expected_return_date' in vals
        if reset_alerts:
            vals = dict(vals, **{
                'strx_return_alert_two_days_sent': False,
                'strx_return_alert_today_sent': False,
                'strx_return_alert_overdue_sent': False,
            })
        res = super().write(vals)
        if {
            'state', 'lot_ids', 'strx_expected_return_date', 'order_line_id',
        } & set(vals):
            returned = self.filtered(lambda alloc: alloc.state != 'on_rent')
            returned._strx_close_open_return_alert_activities()
            self._strx_schedule_due_return_alerts_now()
        if 'lot_ids' in vals:
            for alloc in self:
                added = alloc.lot_ids - old_lots_by_alloc[alloc.id]
                alloc._strx_assert_lot_selectable(added)
            self._strx_sync_legacy_lot_id()
        if allocated_serial_changes:
            self._strx_apply_allocated_serial_changes(allocated_serial_changes)
        return res

    def _strx_sync_legacy_lot_id(self):
        for alloc in self:
            first_lot = alloc.lot_ids[:1]
            if alloc.lot_id != first_lot:
                super(StrxCabinAllocation, alloc.with_context(
                    strx_sync_legacy_lot_id=True)).write({
                        'lot_id': first_lot.id or False,
                    })

    # ------------------------------------------------------------- constraints
    @api.constrains('lot_ids', 'product_id')
    def _check_spec_match(self):
        """The allocated serial must be of the committed specification."""
        for alloc in self:
            mismatched = alloc.lot_ids.filtered(
                lambda lot: alloc.product_id and lot.product_id != alloc.product_id)
            if mismatched:
                lot = mismatched[0]
                raise ValidationError(_(
                    "Specification mismatch on %(ref)s.\n"
                    "Required: %(req)s (%(req_code)s).\n"
                    "Allocated serial %(serial)s is %(got)s (%(got_code)s).\n"
                    "Allocate a unit of the correct specification or raise a "
                    "substitution request.",
                    ref=alloc.name,
                    req=alloc.product_id.strx_cabin_spec or alloc.product_id.display_name,
                    req_code=alloc.product_id.default_code or '-',
                    serial=lot.name,
                    got=lot.product_id.strx_cabin_spec or lot.product_id.display_name,
                    got_code=lot.product_id.default_code or '-',
                ))

    @api.constrains('lot_ids', 'state', 'strx_date_out', 'strx_expected_return_date')
    def _check_no_overlap(self):
        """The same serial cannot back two overlapping active allocations."""
        for alloc in self:
            if not alloc.lot_ids or alloc.state not in ACTIVE_STATES:
                continue
            others = self.search([
                ('id', '!=', alloc.id),
                ('lot_ids', 'in', alloc.lot_ids.ids),
                ('state', 'in', ACTIVE_STATES),
            ])
            for other in others:
                if alloc._strx_periods_overlap(other):
                    serial = (alloc.lot_ids & other.lot_ids)[:1]
                    raise ValidationError(_(
                        "Serial %(serial)s is already allocated on %(other)s over an "
                        "overlapping period. A unit cannot back two overlapping rentals.",
                        serial=serial.name, other=other.name))

    @api.constrains('lot_ids', 'order_line_id')
    def _check_serial_quantity_limit(self):
        for alloc in self:
            if len(alloc.lot_ids) > alloc.required_serial_count:
                raise ValidationError(_(
                    "Rental line %(line)s requires %(required)s serials; "
                    "%(selected)s were selected. The selected count cannot exceed "
                    "the ordered quantity.",
                    line=alloc.order_line_id.display_name,
                    required=alloc.required_serial_count,
                    selected=len(alloc.lot_ids)))

    def _strx_periods_overlap(self, other):
        """Two ranges overlap unless one clearly ends before the other starts.

        Missing bounds are treated as open-ended, so an allocation with no dates
        conservatively conflicts with any other active allocation of the same serial.
        """
        a_start, a_end = self.strx_date_out, self.strx_expected_return_date
        b_start, b_end = other.strx_date_out, other.strx_expected_return_date
        if a_end and b_start and a_end < b_start:
            return False
        if b_end and a_start and b_end < a_start:
            return False
        return True

    # ---------------------------------------------------------- return alerts
    @api.model
    def _strx_logistics_return_alert_users(self):
        group = self.env.ref('stock.group_stock_manager', raise_if_not_found=False)
        users = group.all_user_ids.filtered(lambda user: user.active) if group else self.env['res.users']
        if not users:
            group = self.env.ref('stock.group_stock_user', raise_if_not_found=False)
            users = group.all_user_ids.filtered(lambda user: user.active) if group else users
        settings_group = self.env.ref('base.group_system', raise_if_not_found=False)
        settings_users = settings_group.all_user_ids if settings_group else self.env['res.users']
        dedicated_users = users - settings_users
        return dedicated_users or users or self.env.user

    def _strx_has_open_return_shipment(self):
        self.ensure_one()
        if not self.lot_ids:
            return False
        if 'strx.cabin.shipping.order' not in self.env:
            return False
        return bool(self.env['strx.cabin.shipping.order'].search_count([
            ('order_id', '=', self.order_id.id),
            ('movement_type', '=', 'return'),
            ('state', 'not in', ('delivered', 'cancel')),
            ('lot_ids', 'in', self.lot_ids.ids),
        ]))

    @api.model
    def _cron_schedule_return_alerts(self):
        self.search([
            ('state', '!=', 'on_rent'),
            '|', '|',
            ('strx_return_alert_two_days_sent', '=', True),
            ('strx_return_alert_today_sent', '=', True),
            ('strx_return_alert_overdue_sent', '=', True),
        ])._strx_close_open_return_alert_activities()
        allocations = self.search([
            ('state', '=', 'on_rent'),
            ('lot_ids', '!=', False),
            ('strx_expected_return_date', '!=', False),
        ])
        companies = allocations.mapped('company_id') or self.env.company
        for company in companies:
            company_allocations = allocations.filtered(
                lambda alloc: (alloc.company_id or self.env.company) == company)
            tz, utc_now, local_now, today = self._strx_company_time_context(company)
            _logger.info(
                "Cabin return reminder monitor: company=%s timezone=%s "
                "utc_now=%s local_now=%s today=%s allocations=%s",
                company.display_name,
                tz,
                utc_now.strftime('%Y-%m-%d %H:%M:%S %Z'),
                local_now.strftime('%Y-%m-%d %H:%M:%S %Z%z'),
                today,
                len(company_allocations),
            )
            company_allocations._strx_schedule_return_alerts(
                today=today)

    @api.model
    def _strx_company_timezone(self, company=None):
        company = company or self.env.company
        tz = False
        if 'resource_calendar_id' in company._fields and company.resource_calendar_id:
            tz = company.resource_calendar_id.tz
        tz = tz or company.partner_id.tz or self.env.user.tz or 'Asia/Riyadh'
        try:
            pytz.timezone(tz)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "Invalid timezone %s on company %s; falling back to Asia/Riyadh",
                tz,
                company.display_name,
            )
            tz = 'Asia/Riyadh'
        return tz

    @api.model
    def _strx_company_time_context(self, company=None):
        tz_name = self._strx_company_timezone(company)
        utc_now = pytz.utc.localize(datetime.utcnow())
        local_now = utc_now.astimezone(pytz.timezone(tz_name))
        return tz_name, utc_now, local_now, local_now.date()

    @api.model
    def _strx_company_today(self, company=None):
        return self._strx_company_time_context(company)[3]

    @api.model
    def _strx_return_alert_non_business_weekdays(self):
        """Weekdays excluded from return-alert business-day counting.

        Python weekday: Monday=0 ... Sunday=6. The current business rule excludes
        Friday only. Future official holidays can be added by extending
        _strx_is_return_alert_business_day without changing callers.
        """
        return {4}

    @api.model
    def _strx_is_return_alert_business_day(self, day):
        day = fields.Date.to_date(day)
        return day.weekday() not in self._strx_return_alert_non_business_weekdays()

    @api.model
    def _strx_business_days_before_return(self, return_date, business_days=2):
        day = fields.Date.to_date(return_date)
        remaining = business_days
        while remaining:
            day -= timedelta(days=1)
            if self._strx_is_return_alert_business_day(day):
                remaining -= 1
        return day

    def _strx_schedule_return_alerts(self, today=None):
        today = fields.Date.to_date(today or self._strx_company_today())
        activity_type = self.env.ref('mail.mail_activity_data_todo',
                                     raise_if_not_found=False)
        if not activity_type:
            return
        users = self._strx_logistics_return_alert_users()
        for alloc in self:
            if alloc.state != 'on_rent' or not alloc.strx_expected_return_date:
                continue
            if alloc._strx_has_completed_return_shipment():
                alloc._strx_close_open_return_alert_activities()
                continue
            if alloc._strx_has_open_return_shipment():
                continue
            phase = alloc._strx_return_alert_phase(today)
            if not phase:
                continue
            alloc._strx_send_return_alert_phase(phase, today, users, activity_type)

    def _strx_schedule_due_return_alerts_now(self):
        if self.env.context.get('strx_skip_return_alerts'):
            return
        due = self.filtered(
            lambda alloc: alloc.state == 'on_rent'
            and alloc.lot_ids
            and alloc.strx_expected_return_date)
        companies = due.mapped('company_id') or self.env.company
        for company in companies:
            company_due = due.filtered(
                lambda alloc: (alloc.company_id or self.env.company) == company)
            company_due._strx_schedule_return_alerts(
                today=self._strx_company_today(company))

    def _strx_return_alert_phase(self, today):
        self.ensure_one()
        today = fields.Date.to_date(today)
        return_date = fields.Date.to_date(self.strx_expected_return_date)
        if return_date < today:
            return 'overdue'
        if return_date == today:
            return 'today'
        if self._strx_business_days_before_return(return_date, 2) == today:
            return 'two_days'
        return False

    def _strx_return_alert_sent_field(self, phase):
        return {
            'two_days': 'strx_return_alert_two_days_sent',
            'today': 'strx_return_alert_today_sent',
            'overdue': 'strx_return_alert_overdue_sent',
        }[phase]

    def _strx_return_alert_target_record(self):
        self.ensure_one()
        if self.lot_ids and 'strx.cabin.shipping.order' in self.env:
            shipment = self.env['strx.cabin.shipping.order'].search([
                ('order_id', '=', self.order_id.id),
                ('lot_ids', 'in', self.lot_ids.ids),
                ('movement_type', 'in', ('delivery', 'site_transfer')),
                ('state', '!=', 'cancel'),
            ], order='id desc', limit=1)
            if shipment:
                return shipment
        return self

    def _strx_return_alert_activity_targets(self):
        self.ensure_one()
        targets = [self]
        if self.lot_ids and 'strx.cabin.shipping.order' in self.env:
            shipments = self.env['strx.cabin.shipping.order'].search([
                ('order_id', '=', self.order_id.id),
                ('lot_ids', 'in', self.lot_ids.ids),
                ('movement_type', 'in', ('delivery', 'site_transfer')),
                ('state', '!=', 'cancel'),
            ])
            targets.extend(shipments)
        return targets

    def _strx_has_completed_return_shipment(self):
        self.ensure_one()
        if not self.lot_ids or 'strx.cabin.shipping.order' not in self.env:
            return False
        return bool(self.env['strx.cabin.shipping.order'].search_count([
            ('order_id', '=', self.order_id.id),
            ('movement_type', '=', 'return'),
            ('state', '=', 'delivered'),
            ('lot_ids', 'in', self.lot_ids.ids),
        ]))

    @api.model
    def _strx_return_alert_summary(self, env, phase, ref):
        """The alert summary for one phase, in `env`'s language.

        The literals live here rather than in a lookup table because term
        extraction only sees strings written inside ``_()``; a table keyed at
        runtime would export nothing and never be translated.
        """
        if phase == 'two_days':
            return env._("Shipment %(ref)s — two business days until return", ref=ref)
        if phase == 'today':
            return env._("Shipment %(ref)s — return is due today", ref=ref)
        return env._("Shipment %(ref)s — return is overdue", ref=ref)

    def _strx_return_alert_summaries(self):
        """Every active language's rendering of this record's alert summaries.

        Return alerts use the generic To-Do activity type, so they can only be
        told apart from other To-Dos on the same record by their summary. That
        used to be an `ilike` against the English and Arabic wording, which
        missed any third language and matched unrelated To-Dos containing the
        word "return". Rendering the exact strings in every installed language
        makes the match precise and language-independent.
        """
        self.ensure_one()
        ref = self._strx_return_alert_reference()
        summaries = set()
        for code, _name in self.env['res.lang'].get_installed():
            env = self.with_context(lang=code).env
            for phase in ('two_days', 'today', 'overdue'):
                summaries.add(self._strx_return_alert_summary(env, phase, ref))
        return list(summaries)

    def _strx_return_alert_reference(self):
        self.ensure_one()
        return self._strx_return_alert_target_record().name or self.name

    def _strx_return_alert_texts(self, user, phase, today):
        self.ensure_one()
        ref = self._strx_return_alert_reference()
        return_date = fields.Date.to_date(self.strx_expected_return_date)
        overdue_days = max((fields.Date.to_date(today) - return_date).days, 0)
        # The alert is addressed to `user`, so it is written in THAT user's
        # language rather than the acting user's. `env._` is the explicit form
        # that binds the translation to a chosen language.
        env = self.with_context(lang=user.lang or self.env.lang).env
        summary = self._strx_return_alert_summary(env, phase, ref)
        note = env._(
            "Return date: %(date)s\n"
            "Overdue days: %(days)s\n"
            "Customer: %(customer)s\n"
            "Serial: %(serial)s",
            date=self.strx_expected_return_date,
            days=overdue_days,
            customer=self.partner_id.display_name or '-',
            serial=", ".join(self.lot_ids.mapped('name')) or '-',
        )
        return summary, note

    def _strx_send_return_alert_phase(self, phase, today, users, activity_type):
        self.ensure_one()
        sent_field = self._strx_return_alert_sent_field(phase)
        if self[sent_field]:
            return
        target = self._strx_return_alert_target_record()
        model = self.env['ir.model']._get(target._name)
        if not model:
            return
        Activity = self.env['mail.activity']
        for user in users:
            summary, note = self._strx_return_alert_texts(user, phase, today)
            exists = Activity.search_count([
                ('res_model_id', '=', model.id),
                ('res_id', '=', target.id),
                ('activity_type_id', '=', activity_type.id),
                ('user_id', '=', user.id),
                ('summary', '=', summary),
            ])
            if not exists:
                Activity.create({
                    'activity_type_id': activity_type.id,
                    'res_model_id': model.id,
                    'res_id': target.id,
                    'user_id': user.id,
                    'date_deadline': fields.Date.to_date(today),
                    'summary': summary,
                    'note': note,
                })
        target.message_post(
            body=self._strx_return_alert_texts(self.env.user, phase, today)[1],
            subject=self._strx_return_alert_texts(self.env.user, phase, today)[0],
            subtype_xmlid='mail.mt_note')
        self.with_context(strx_skip_return_alerts=True).write({sent_field: True})

    def _strx_close_open_return_alert_activities(self):
        activity_type = self.env.ref('mail.mail_activity_data_todo',
                                     raise_if_not_found=False)
        if not activity_type:
            return
        Activity = self.env['mail.activity']
        for alloc in self:
            for target in alloc._strx_return_alert_activity_targets():
                model = self.env['ir.model']._get(target._name)
                activities = Activity.search([
                    ('res_model_id', '=', model.id),
                    ('res_id', '=', target.id),
                    ('activity_type_id', '=', activity_type.id),
                    ('summary', 'in', alloc._strx_return_alert_summaries()),
                ])
                if activities:
                    activities.action_feedback(
                        feedback=_('Return completed; reminder closed.'))

    # ----------------------------------------------- allocated serial changes
    def _strx_apply_allocated_serial_changes(self, old_lots_by_alloc):
        for alloc in self:
            old_lots = old_lots_by_alloc.get(alloc.id, self.env['stock.lot'])
            if alloc.state != 'allocated':
                continue
            new_lots = alloc.lot_ids
            if old_lots == new_lots:
                continue
            removed_lots = old_lots - new_lots
            added_lots = new_lots - old_lots
            releasable = removed_lots.filtered(
                lambda lot: lot.strx_readiness_state == 'allocated')
            if releasable:
                releasable._strx_set_readiness(
                    'available',
                    reason=_("Replaced on allocation %(ref)s", ref=alloc.name))
            to_allocate = added_lots.filtered(
                lambda lot: lot.strx_readiness_state != 'allocated')
            if to_allocate:
                to_allocate._strx_set_readiness(
                    'allocated',
                    reason=_("Allocated to %(ref)s", ref=alloc.name))
            updated_shipments = alloc._strx_sync_draft_shipments_after_serial_change(
                removed_lots, added_lots)
            alloc._strx_notify_allocated_serial_change(
                old_lots, new_lots, updated_shipments)

    def _strx_sync_draft_shipments_after_serial_change(self, old_lots, new_lots):
        self.ensure_one()
        if 'strx.cabin.shipping.order' not in self.env or not old_lots:
            return self.env['ir.model']
        shipments = self.env['strx.cabin.shipping.order'].search([
            ('order_id', '=', self.order_id.id),
            ('movement_type', 'in', ('delivery', 'site_transfer')),
            ('state', '=', 'draft'),
            ('lot_ids', 'in', old_lots.ids),
        ])
        for shipment in shipments:
            commands = [(3, lot.id) for lot in old_lots]
            commands.extend((4, lot.id) for lot in new_lots)
            shipment.with_context(strx_shipping_autofill_lots=True).write({
                'lot_ids': commands,
            })
        return shipments

    def _strx_allocated_serial_change_texts(self, user, old_lots, new_lots,
                                            updated_shipments):
        self.ensure_one()
        # Written in the recipient's language, not the acting user's.
        env = self.with_context(lang=user.lang or self.env.lang).env
        summary = env._("Allocation %(ref)s — allocated serial changed", ref=self.name)
        body = [
            env._("The serial was changed on an allocated cabin allocation."),
            env._("Allocation: %s") % self.name,
            env._("Rental Order: %s") % (self.order_id.name or '-'),
            env._("Customer: %s") % (self.partner_id.display_name or '-'),
            env._("From: %s") % (", ".join(old_lots.mapped('name')) or '-'),
            env._("To: %s") % (", ".join(new_lots.mapped('name')) or '-'),
        ]
        if updated_shipments:
            body.append(
                env._("Draft shipments updated automatically: %s")
                % ", ".join(updated_shipments.mapped('name')))
        body.append(env._("Review the allocation and open shipments before dispatch."))
        return summary, "<br/>".join(body)

    def _strx_notify_allocated_serial_change(self, old_lots, new_lots,
                                             updated_shipments):
        self.ensure_one()
        activity_type = self.env.ref('mail.mail_activity_data_todo',
                                     raise_if_not_found=False)
        if not activity_type:
            return
        users = self._strx_logistics_return_alert_users()
        model = self.env['ir.model']._get(self._name)
        deadline = self._strx_company_today(self.company_id)
        subject, body = self._strx_allocated_serial_change_texts(
            self.env.user, old_lots, new_lots, updated_shipments)
        self.message_post(body=body, subject=subject, subtype_xmlid='mail.mt_note')
        for user in users:
            summary, note = self._strx_allocated_serial_change_texts(
                user, old_lots, new_lots, updated_shipments)
            self.env['mail.activity'].create({
                'activity_type_id': activity_type.id,
                'res_model_id': model.id,
                'res_id': self.id,
                'user_id': user.id,
                'date_deadline': deadline,
                'summary': summary,
                'note': note,
            })
        for shipment in updated_shipments:
            shipment.message_post(body=body, subject=subject,
                                  subtype_xmlid='mail.mt_note')

    # ---------------------------------------------------------------- actions
    def action_allocate(self):
        for alloc in self:
            if not alloc.lot_ids:
                raise UserError(_("Select the required serials to allocate first."))
            if len(alloc.lot_ids) < alloc.required_serial_count:
                raise UserError(_(
                    "Serial selection is incomplete: selected %(selected)s of "
                    "%(required)s. Select %(remaining)s more before allocating.",
                    selected=len(alloc.lot_ids),
                    required=alloc.required_serial_count,
                    remaining=alloc.required_serial_count - len(alloc.lot_ids)))
            if alloc.order_id.state != 'sale':
                raise UserError(_(
                    "The rental order %(order)s must be confirmed before allocating.",
                    order=alloc.order_id.name))
            # Re-assert at commit time: a unit can stop being Available between the
            # allocation being drafted and logistics actioning it. Skipped when this
            # allocation already holds the unit, so re-actioning stays idempotent.
            if alloc.state != 'allocated':
                alloc._strx_assert_lot_selectable(alloc.lot_ids)
            # _check_spec_match / _check_no_overlap re-run on this write.
            alloc.state = 'allocated'
            alloc.lot_ids._strx_set_readiness(
                'allocated', reason=_("Allocated to %(ref)s", ref=alloc.name))

    def action_cancel(self):
        self._strx_release_lots(reason_tmpl=_("Allocation %(ref)s cancelled"))
        self.write({'state': 'cancel'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def _strx_validate_return_assessment_start(self):
        self.ensure_one()
        if self.state != 'returned':
            raise UserError(_(
                "Only a returned cabin allocation can be assessed."))
        if not self.lot_ids:
            raise UserError(_(
                "This returned allocation has no cabin serial to assess."))
        invalid_lot = self.lot_ids.filtered(
            lambda lot: lot.strx_readiness_state
            not in {'returned', 'in_inspection', 'in_cleaning'})[:1]
        if invalid_lot:
            raise UserError(_(
                "Cabin %(serial)s is now %(state)s and cannot be assessed from "
                "this returned allocation.",
                serial=invalid_lot.name,
                state=invalid_lot.strx_state_label
                    or invalid_lot.strx_readiness_state))

    def action_open_return_assessment(self):
        self.ensure_one()
        self._strx_validate_return_assessment_start()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Condition Assessment'),
            'res_model': 'strx.cabin.return.assessment.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'strx_cabin_allocation.view_strx_return_assessment_wizard_form').id,
            'target': 'new',
            'context': {
                'default_allocation_id': self.id,
                'active_id': self.id,
                'active_model': self._name,
            },
        }

    def action_mark_available(self):
        """Compatibility alias for integrations using the former button method."""
        return self.action_open_return_assessment()

    # ------------------------------------------------------------------ unlink
    def unlink(self):
        # A deleted allocation must never strand its serial in 'allocated', or the
        # unit vanishes from every selection picker permanently.
        self._strx_release_lots(reason_tmpl=_("Allocation %(ref)s deleted"))
        return super().unlink()

    def _strx_release_lots(self, reason_tmpl):
        """Return each still-held serial to Available.

        Guarded on the LOT's readiness ('allocated'), not the allocation's state, so
        a unit that has already left the yard (dispatched / on_rent / …) is left
        untouched. Safe to call from cancel and unlink alike.
        """
        for alloc in self:
            lots = alloc.lot_ids.filtered(
                lambda lot: lot.strx_readiness_state == 'allocated')
            if lots:
                lots._strx_set_readiness(
                    'available', reason=reason_tmpl % {'ref': alloc.name})
