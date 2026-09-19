# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class GrRentalOrder(models.Model):
    _name = 'gr.rental.order'
    _description = 'Generator Rental Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    # States in which the asset is considered committed to this order, so the
    # same asset cannot be committed to another active order (double-booking).
    _ACTIVE_ASSET_STATES = (
        'reserved', 'dispatched', 'installed', 'on_rent', 'off_hire_requested')

    # ------------------------------------------------------------------
    name = fields.Char(
        string='Order Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True, index=True)
    site_id = fields.Many2one(
        'gr.customer.site', string='Site', tracking=True,
        domain="[('partner_id', '=', partner_id)]")
    contract_id = fields.Many2one(
        'gr.rental.contract', string='Contract', tracking=True,
        domain="[('partner_id', '=', partner_id)]")
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Generator Asset', tracking=True, index=True,
        domain="[('status', '=', 'available')]")
    requested_kva = fields.Float(string='Requested kVA')

    # Planned / actual timings
    date_requested = fields.Datetime(
        string='Date Requested', default=fields.Datetime.now, index=True)
    planned_dispatch_datetime = fields.Datetime(
        string='Planned Dispatch', index=True)
    planned_install_datetime = fields.Datetime(
        string='Planned Install', index=True)
    actual_dispatch_datetime = fields.Datetime(
        string='Actual Dispatch', readonly=True, index=True)
    actual_install_datetime = fields.Datetime(
        string='Actual Install', readonly=True, index=True)
    planned_return_datetime = fields.Datetime(
        string='Planned Return', index=True)
    actual_return_datetime = fields.Datetime(
        string='Actual Return', readonly=True, index=True)
    availability_state = fields.Selection([
        ('not_ready', 'Not Ready'),
        ('available', 'Available'),
        ('unavailable', 'Unavailable'),
    ], string='Availability', compute='_compute_availability_state')
    availability_message = fields.Text(
        string='Availability Details', compute='_compute_availability_state')

    # Meter readings
    start_meter_reading = fields.Float(string='Start Meter Reading', tracking=True)
    end_meter_reading = fields.Float(string='End Meter Reading', tracking=True)

    # People
    delivery_driver_id = fields.Many2one('res.users', string='Delivery Driver')
    installation_technician_id = fields.Many2one('res.users', string='Installation Technician')
    return_technician_id = fields.Many2one('res.users', string='Return Technician')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('reserved', 'Reserved'),
        ('dispatched', 'Dispatched'),
        ('installed', 'Installed'),
        ('on_rent', 'On Rent'),
        ('off_hire_requested', 'Off-Hire Requested'),
        ('returned', 'Returned'),
        ('inspection', 'Inspection'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False,
        index=True)

    dispatch_note = fields.Text(string='Dispatch Note')
    installation_note = fields.Text(string='Installation Note')
    return_note = fields.Text(string='Return Note')
    customer_receiver_name = fields.Char(string='Customer Receiver Name')
    customer_receiver_signature = fields.Binary(string='Receiver Signature')
    customer_return_signature = fields.Binary(string='Return Signature')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')

    checklist_ids = fields.One2many(
        'gr.rental.order.checklist', 'order_id', string='Checklist')
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, string='Currency')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The rental order reference must be unique per company.",
    )

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS gr_rental_order_availability_asset_idx
                ON gr_rental_order
             (company_id, state, asset_id,
              planned_dispatch_datetime, planned_return_datetime)
             WHERE asset_id IS NOT NULL
        """)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    def _availability_engine(self):
        return self.env['gr.rental.availability']

    def _availability_commit_states(self):
        return (
            'confirmed', 'reserved', 'dispatched', 'installed', 'on_rent',
            'off_hire_requested', 'returned', 'inspection',
        )

    def _availability_validation_fields(self):
        return {
            'asset_id', 'company_id', 'date_requested',
            'planned_dispatch_datetime', 'planned_install_datetime',
            'actual_dispatch_datetime', 'actual_install_datetime',
            'planned_return_datetime', 'actual_return_datetime', 'state',
        }

    def _availability_should_touch_current_status(self):
        self.ensure_one()
        return self._availability_engine().order_starts_now_or_past(self)

    @api.depends('asset_id', 'company_id', 'date_requested',
                 'planned_dispatch_datetime', 'planned_install_datetime',
                 'actual_dispatch_datetime', 'actual_install_datetime',
                 'planned_return_datetime', 'actual_return_datetime', 'state')
    def _compute_availability_state(self):
        engine = self._availability_engine()
        for order in self:
            result = engine.order_availability_result(order)
            order.availability_state = result['state']
            order.availability_message = result['message']

    def _check_order_availability(self, lock=False, exception='user'):
        engine = self._availability_engine()
        for order in self:
            if not engine.order_has_physical_targets(order):
                continue
            engine.assert_order_available(order, lock=lock, exception=exception)
        return True

    def _should_validate_availability_write(self, vals):
        if self.env.context.get('gr_skip_availability_validation'):
            return False
        changed = set(vals) & self._availability_validation_fields()
        if not changed:
            return False
        # Returning/closing writes happen in several small internal assignments.
        # The actual return datetime write, not the intermediate state flip, is
        # the meaningful availability update.
        if changed == {'state'} and vals.get('state') in (
                'returned', 'inspection', 'closed', 'cancelled', 'draft'):
            return False
        return True

    # ------------------------------------------------------------------
    # Create: sequence
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('gr.rental.order')
                vals['name'] = seq or _('New')
        return super().create(vals_list)

    def write(self, vals):
        should_validate = self._should_validate_availability_write(vals)
        res = super().write(vals)
        if should_validate:
            orders = self.filtered(
                lambda order: order.state in order._availability_commit_states())
            orders._check_order_availability(
                lock=vals.get('state') in ('confirmed', 'reserved'),
                exception='validation')
        return res

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('start_meter_reading', 'end_meter_reading')
    def _check_meter_order(self):
        for o in self:
            if o.end_meter_reading and o.start_meter_reading and \
                    o.end_meter_reading < o.start_meter_reading:
                raise ValidationError(_(
                    "End meter reading cannot be less than the start meter reading."))

    # ------------------------------------------------------------------
    # Double-booking guard: an asset committed to another active order
    # cannot be committed here. Checked on reservation.
    # ------------------------------------------------------------------
    def _check_asset_not_double_booked(self):
        self._check_order_availability(lock=False, exception='user')

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_confirm(self):
        for o in self:
            if o.state != 'draft':
                raise UserError(_("Only draft orders can be confirmed."))
            if not o.contract_id:
                raise UserError(_("A contract is required to confirm the order."))
            if o.contract_id.state not in ('approved', 'active'):
                raise UserError(_(
                    "Contract %s must be approved or active before confirming the order.")
                    % o.contract_id.name)
            o._check_order_availability(lock=True, exception='user')
            o.state = 'confirmed'
        return True

    def action_reserve(self):
        for o in self:
            if o.state != 'confirmed':
                raise UserError(_("Only confirmed orders can reserve an asset."))
            if not o.asset_id:
                raise UserError(_("Select a generator asset before reserving."))
            o._check_order_availability(lock=True, exception='user')
            o.state = 'reserved'
            if o._availability_should_touch_current_status():
                o.asset_id.status = 'reserved'
            o.asset_id.message_post(
                body=_("Reserved for order %s.") % o.name,
                message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def action_dispatch(self):
        for o in self:
            if o.state != 'reserved':
                raise UserError(_("Only reserved orders can be dispatched."))
            if o.asset_id.maintenance_overdue:
                raise UserError(_(
                    "Generator %s has overdue maintenance; dispatch is blocked.")
                    % o.asset_id.display_name)
            o.state = 'dispatched'
            o.actual_dispatch_datetime = fields.Datetime.now()
            o.asset_id.status = 'in_transit'
        return True

    def action_install(self):
        for o in self:
            if o.state != 'dispatched':
                raise UserError(_("Only dispatched orders can be installed."))
            if o.start_meter_reading < 0:
                raise UserError(_(
                    "A valid (non-negative) start meter reading is required to "
                    "install."))
            if o.start_meter_reading < o.asset_id.current_hour_meter:
                raise UserError(_(
                    "Start meter (%(start)s) cannot be below the asset's current "
                    "meter (%(cur)s). Use the meter-correction wizard if needed.",
                    start=o.start_meter_reading, cur=o.asset_id.current_hour_meter))
            o.state = 'installed'
            o.actual_install_datetime = fields.Datetime.now()
            # Bind the asset to this deployment.
            o.asset_id.with_context(gr_meter_correction=True).write({
                'status': 'on_rent',
                'current_hour_meter': o.start_meter_reading,
                'current_customer_id': o.partner_id.id,
                'current_site_ref': o.site_id.display_name if o.site_id else False,
                'current_contract_ref': o.contract_id.name if o.contract_id else False,
                'current_rental_order_ref': o.name,
            })
        return True

    def action_start_rental(self):
        for o in self:
            if o.state != 'installed':
                raise UserError(_("Only installed orders can start rental."))
            o.state = 'on_rent'
        return True

    def action_request_off_hire(self):
        for o in self:
            if o.state != 'on_rent':
                raise UserError(_("Only on-rent orders can request off-hire."))
            o.state = 'off_hire_requested'
        return True

    def action_return(self):
        for o in self:
            if o.state not in ('on_rent', 'off_hire_requested'):
                raise UserError(_("Only on-rent or off-hire orders can be returned."))
            if o.end_meter_reading < 0:
                raise UserError(_(
                    "A valid (non-negative) end meter reading is required to "
                    "return."))
            if o.end_meter_reading < o.start_meter_reading:
                raise UserError(_(
                    "End meter (%(end)s) cannot be below the start meter (%(start)s).",
                    end=o.end_meter_reading, start=o.start_meter_reading))
            o.state = 'returned'
            o.actual_return_datetime = fields.Datetime.now()
            # Final meter updates the asset; asset awaits inspection.
            o.asset_id.with_context(gr_meter_correction=True).write({
                'status': 'returned_pending_inspection',
                'current_hour_meter': o.end_meter_reading,
                'current_customer_id': False,
                'current_site_ref': False,
                'current_contract_ref': False,
                'current_rental_order_ref': False,
            })
        return True

    def action_start_inspection(self):
        for o in self:
            if o.state != 'returned':
                raise UserError(_("Only returned orders can start inspection."))
            o.state = 'inspection'
        return True

    def action_close(self):
        for o in self:
            if o.state != 'inspection':
                raise UserError(_("Only orders under inspection can be closed."))
            o.state = 'closed'
            # Release asset to available only if maintenance is not overdue.
            if o.asset_id and not o.asset_id.maintenance_overdue \
                    and o.asset_id.status == 'returned_pending_inspection':
                o.asset_id.status = 'available'
        return True

    def action_cancel(self):
        for o in self:
            if o.state in ('closed',):
                raise UserError(_("A closed order cannot be cancelled."))
            # If the asset was committed, release it back to available.
            if o.asset_id and o.asset_id.status in self._ACTIVE_ASSET_STATES \
                    and o.asset_id.current_rental_order_ref == o.name:
                o.asset_id.with_context(gr_meter_correction=True).write({
                    'status': 'available',
                    'current_customer_id': False,
                    'current_site_ref': False,
                    'current_contract_ref': False,
                    'current_rental_order_ref': False,
                })
            elif o.asset_id and o.asset_id.status == 'reserved':
                o.asset_id.status = 'available'
            o.state = 'cancelled'
        return True

    def action_reset_to_draft(self):
        for o in self:
            if o.state != 'cancelled':
                raise UserError(_("Only cancelled orders can return to draft."))
            o.state = 'draft'
        return True
