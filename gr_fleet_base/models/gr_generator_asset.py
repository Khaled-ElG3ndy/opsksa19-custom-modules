# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class GrGeneratorAsset(models.Model):
    _name = 'gr.generator.asset'
    _description = 'Generator Asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code, name'

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Name', required=True, tracking=True,
        help="Display name for the generator (e.g. 'CAT 500 kVA #3').")
    code = fields.Char(
        string='Asset Code', required=True, copy=False, tracking=True,
        default=lambda self: _('New'),
        help="Unique internal code. Auto-assigned from the GR/ASSET sequence.")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', store=True,
        string='Currency')
    active = fields.Boolean(default=True, tracking=True)

    product_id = fields.Many2one(
        'product.product', string='Product',
        help="Optional commercial product this generator is rented as.")

    # ------------------------------------------------------------------
    # Technical specification
    # ------------------------------------------------------------------
    brand = fields.Char(string='Brand', tracking=True)
    model_name = fields.Char(string='Model', tracking=True)
    serial_number = fields.Char(
        string='Serial Number', copy=False, tracking=True,
        help="Manufacturer serial number. Unique per company.")
    manufacturing_year = fields.Integer(string='Manufacturing Year')
    kva_rating = fields.Float(string='kVA Rating', tracking=True)
    fuel_type = fields.Selection([
        ('diesel', 'Diesel'),
        ('petrol', 'Petrol'),
        ('gas', 'Gas'),
        ('hybrid', 'Hybrid'),
        ('other', 'Other'),
    ], string='Fuel Type', default='diesel', tracking=True)
    engine_model = fields.Char(string='Engine Model')
    alternator_model = fields.Char(string='Alternator Model')
    fuel_tank_capacity = fields.Float(string='Fuel Tank Capacity (L)')

    # ------------------------------------------------------------------
    # Hour-meter tracking
    # ------------------------------------------------------------------
    current_hour_meter = fields.Float(
        string='Current Hour Meter', default=0.0, tracking=True,
        help="Latest known engine-hour reading. Never decreases except via the "
             "controlled meter-correction wizard.")
    last_verified_hour_meter = fields.Float(
        string='Last Verified Meter', default=0.0, readonly=True, copy=False,
        help="Last reading verified on-site. The current meter may not be set "
             "below this except through an approved correction.")
    last_verified_date = fields.Datetime(
        string='Last Verified On', readonly=True, copy=False)
    last_verified_by = fields.Many2one(
        'res.users', string='Last Verified By', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Status / state machine
    # ------------------------------------------------------------------
    status = fields.Selection([
        ('available', 'Available'),
        ('reserved', 'Reserved'),
        ('in_transit', 'In Transit'),
        ('installed', 'Installed'),
        ('on_rent', 'On Rent'),
        ('maintenance_due', 'Maintenance Due'),
        ('under_maintenance', 'Under Maintenance'),
        ('breakdown', 'Breakdown'),
        ('returned_pending_inspection', 'Returned - Pending Inspection'),
        ('unavailable', 'Unavailable'),
        ('retired', 'Retired'),
    ], string='Status', default='available', required=True, tracking=True,
        copy=False, index=True)

    # ------------------------------------------------------------------
    # Operational links (kept as plain m2o here; downstream modules in later
    # milestones add the inverse relations and smart buttons)
    # ------------------------------------------------------------------
    depot_location_id = fields.Many2one(
        'res.partner', string='Depot / Yard',
        domain="[('is_company', '=', True)]",
        help="Where the generator sits when not deployed.")
    current_customer_id = fields.Many2one(
        'res.partner', string='Current Customer', readonly=True, copy=False)
    # The following are declared as reference-safe Char placeholders in M1 to
    # avoid a dependency on not-yet-built models. Later milestones convert these
    # to proper Many2one fields once the target models exist.
    current_site_ref = fields.Char(
        string='Current Site (ref)', readonly=True, copy=False)
    current_contract_ref = fields.Char(
        string='Current Contract (ref)', readonly=True, copy=False)
    current_rental_order_ref = fields.Char(
        string='Current Rental Order (ref)', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Preventive-maintenance thresholds
    # ------------------------------------------------------------------
    last_pm_hour = fields.Float(string='Last PM at (h)', default=0.0, tracking=True)
    pm_interval_hours = fields.Float(
        string='PM Interval (h)', default=250.0, tracking=True,
        help="Engine hours between preventive-maintenance services.")
    pm_warning_threshold_hours = fields.Float(
        string='PM Warning Before (h)', default=25.0,
        help="Raise a maintenance-due warning this many hours before the next PM.")
    next_pm_hour = fields.Float(
        string='Next PM at (h)', compute='_compute_next_pm_hour',
        store=True, tracking=True)
    maintenance_overdue = fields.Boolean(
        string='Maintenance Overdue', compute='_compute_maintenance_overdue',
        store=True, tracking=True)

    # ------------------------------------------------------------------
    # Profitability (rolled up by later milestones; stored for dashboards)
    # ------------------------------------------------------------------
    revenue_total = fields.Monetary(
        string='Total Revenue', currency_field='currency_id',
        default=0.0, readonly=True)
    cost_total = fields.Monetary(
        string='Total Cost', currency_field='currency_id',
        default=0.0, readonly=True)
    profitability = fields.Monetary(
        string='Profitability', currency_field='currency_id',
        compute='_compute_profitability', store=True)
    utilization_hours_total = fields.Float(
        string='Total Utilization (h)', default=0.0, readonly=True)

    image_1920 = fields.Image(string='Image', max_width=1920, max_height=1920)
    notes = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # SQL constraints
    # ------------------------------------------------------------------
    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        "The asset code must be unique per company.",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('last_pm_hour', 'pm_interval_hours')
    def _compute_next_pm_hour(self):
        for asset in self:
            asset.next_pm_hour = (asset.last_pm_hour or 0.0) + (asset.pm_interval_hours or 0.0)

    @api.depends('current_hour_meter', 'next_pm_hour', 'pm_interval_hours')
    def _compute_maintenance_overdue(self):
        for asset in self:
            # Overdue only when a real interval is configured and the meter has
            # reached or passed the next PM point.
            asset.maintenance_overdue = bool(
                asset.pm_interval_hours and asset.next_pm_hour
                and asset.current_hour_meter >= asset.next_pm_hour
            )

    @api.depends('revenue_total', 'cost_total')
    def _compute_profitability(self):
        for asset in self:
            asset.profitability = (asset.revenue_total or 0.0) - (asset.cost_total or 0.0)

    # ------------------------------------------------------------------
    # Python constraints (server-side, always enforced)
    # ------------------------------------------------------------------
    @api.constrains('current_hour_meter')
    def _check_meter_non_negative(self):
        for asset in self:
            if asset.current_hour_meter < 0:
                raise ValidationError(_(
                    "Current hour meter cannot be negative (asset %s).") % asset.display_name)

    @api.constrains('serial_number', 'company_id')
    def _check_serial_unique_per_company(self):
        for asset in self:
            if not asset.serial_number:
                continue
            dup = self.search_count([
                ('id', '!=', asset.id),
                ('company_id', '=', asset.company_id.id),
                ('serial_number', '=', asset.serial_number),
            ])
            if dup:
                raise ValidationError(_(
                    "Serial number %(sn)s already exists for this company.",
                    sn=asset.serial_number))

    @api.constrains('manufacturing_year')
    def _check_manufacturing_year(self):
        for asset in self:
            if asset.manufacturing_year and not (1950 <= asset.manufacturing_year <= 2100):
                raise ValidationError(_(
                    "Manufacturing year %(y)s is out of a sensible range.",
                    y=asset.manufacturing_year))

    @api.constrains('status', 'maintenance_overdue')
    def _check_available_requires_maintenance_ok(self):
        for asset in self:
            if asset.status == 'available' and asset.maintenance_overdue:
                raise ValidationError(_(
                    "Asset %s cannot be set to Available while maintenance is "
                    "overdue. Complete the preventive maintenance first.")
                    % asset.display_name)

    # ------------------------------------------------------------------
    # Meter-rollback guard (the core audit rule)
    # ------------------------------------------------------------------
    def write(self, vals):
        # A normal edit may never move the meter backwards. The floor is the
        # meter's own current value: you cannot type a number lower than what
        # the meter already reads. The controlled correction wizard sets a
        # context flag to bypass this and is the only legitimate way to
        # decrease a reading (with audit + approval).
        if 'current_hour_meter' in vals and not self.env.context.get('gr_meter_correction'):
            new_value = vals['current_hour_meter']
            for asset in self:
                floor = asset.current_hour_meter or 0.0
                if new_value < floor:
                    raise UserError(_(
                        "Meter for %(asset)s cannot be reduced from %(floor)s h to "
                        "%(new)s h by a normal edit. Use the Meter Correction wizard "
                        "for an audited adjustment.",
                        asset=asset.display_name, floor=floor, new=new_value))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Create: assign sequence code
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('gr.generator.asset')
                vals['code'] = seq or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Status helper actions (guarded transitions)
    # ------------------------------------------------------------------
    def action_set_available(self):
        for asset in self:
            if asset.status == 'breakdown':
                raise UserError(_(
                    "Asset %s is in Breakdown and cannot be made Available "
                    "directly.") % asset.display_name)
            if asset.maintenance_overdue:
                raise UserError(_(
                    "Asset %s has overdue maintenance and cannot be made "
                    "Available.") % asset.display_name)
            asset.status = 'available'
        return True

    def action_set_unavailable(self):
        self.write({'status': 'unavailable'})
        return True

    def action_set_breakdown(self):
        self.write({'status': 'breakdown'})
        for asset in self:
            asset.message_post(
                body=_("Asset marked as Breakdown."),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_retire(self):
        for asset in self:
            # Guard: cannot retire while an active rental reference is set.
            if asset.current_rental_order_ref:
                raise UserError(_(
                    "Asset %s has an active rental order and cannot be retired.")
                    % asset.display_name)
            asset.status = 'retired'
            asset.active = False
        return True

    def action_open_meter_correction(self):
        """Open the controlled meter-correction wizard for this asset."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Meter Correction'),
            'res_model': 'gr.generator.asset.meter.correction.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_asset_id': self.id},
        }
