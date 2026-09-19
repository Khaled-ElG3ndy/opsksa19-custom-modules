# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GrCustomerSite(models.Model):
    _name = 'gr.customer.site'
    _description = 'Customer Site'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code, name'

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(string='Site Name', required=True, tracking=True)
    code = fields.Char(
        string='Site Code', required=True, copy=False, tracking=True,
        default=lambda self: _('New'),
        help="Unique internal code. Auto-assigned from the GR/SITE sequence.")
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True, tracking=True)

    # ------------------------------------------------------------------
    # Customer link (standalone record referencing the partner, not a child
    # contact — keeps operational site data separate from the address book).
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True, tracking=True,
        index=True,
        help="The customer who owns/operates this site.")
    contact_name = fields.Char(string='Site Contact')
    contact_phone = fields.Char(string='Contact Phone')
    contact_email = fields.Char(string='Contact Email')

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------
    region = fields.Char(string='Region')
    city = fields.Char(string='City')
    district = fields.Char(string='District')
    street = fields.Char(string='Street')
    gps_latitude = fields.Float(string='GPS Latitude', digits=(10, 7))
    gps_longitude = fields.Float(string='GPS Longitude', digits=(10, 7))

    site_type = fields.Selection([
        ('construction', 'Construction'),
        ('factory', 'Factory'),
        ('event', 'Event'),
        ('hospital', 'Hospital'),
        ('farm', 'Farm'),
        ('telecom', 'Telecom'),
        ('government', 'Government'),
        ('other', 'Other'),
    ], string='Site Type', default='construction', tracking=True)

    # ------------------------------------------------------------------
    # Load requirements
    # ------------------------------------------------------------------
    required_load_kw = fields.Float(string='Required Load (kW)')
    required_kva = fields.Float(string='Required kVA')
    load_profile_notes = fields.Text(string='Load Profile Notes')

    # ------------------------------------------------------------------
    # Operational notes / policy
    # ------------------------------------------------------------------
    access_instructions = fields.Text(string='Access Instructions')
    safety_requirements = fields.Text(string='Safety Requirements')
    working_hours_policy = fields.Text(string='Working Hours Policy')
    customer_po_required = fields.Boolean(string='Customer PO Required')
    notes = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Smart-button counters. The related models are built in later
    # milestones; the fields are declared now (default 0) so the buttons
    # render, and the compute is wired defensively to whatever models exist.
    # ------------------------------------------------------------------
    contract_count = fields.Integer(
        string='Contracts', compute='_compute_related_counts')
    rental_order_count = fields.Integer(
        string='Rental Orders', compute='_compute_related_counts')
    installed_generator_count = fields.Integer(
        string='Installed Generators', compute='_compute_related_counts')
    hour_log_count = fields.Integer(
        string='Hour Logs', compute='_compute_related_counts')
    maintenance_job_count = fields.Integer(
        string='Maintenance Jobs', compute='_compute_related_counts')

    # ------------------------------------------------------------------
    # SQL constraints
    # ------------------------------------------------------------------
    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        "The site code must be unique per company.",
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _compute_related_counts(self):
        # In M2 these targets do not yet exist; report 0 safely. Later
        # milestones override this compute (or replace it) once the related
        # models are introduced. Using a guarded lookup keeps M2 installable
        # and the buttons functional without a hard dependency.
        for site in self:
            site.contract_count = 0
            site.rental_order_count = 0
            site.installed_generator_count = 0
            site.hour_log_count = 0
            site.maintenance_job_count = 0

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('required_kva')
    def _check_required_kva_positive(self):
        for site in self:
            if site.required_kva and site.required_kva < 0:
                raise ValidationError(_(
                    "Required kVA must be a positive value (site %s).")
                    % site.display_name)

    @api.constrains('required_load_kw')
    def _check_required_load_positive(self):
        for site in self:
            if site.required_load_kw and site.required_load_kw < 0:
                raise ValidationError(_(
                    "Required load (kW) must be a positive value (site %s).")
                    % site.display_name)

    @api.constrains('gps_latitude', 'gps_longitude')
    def _check_gps_range(self):
        for site in self:
            if site.gps_latitude and not (-90.0 <= site.gps_latitude <= 90.0):
                raise ValidationError(_("GPS latitude must be between -90 and 90."))
            if site.gps_longitude and not (-180.0 <= site.gps_longitude <= 180.0):
                raise ValidationError(_("GPS longitude must be between -180 and 180."))

    # ------------------------------------------------------------------
    # Create: assign sequence code
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                seq = self.env['ir.sequence'].next_by_code('gr.customer.site')
                vals['code'] = seq or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Onchange: prefill contact details from the customer (UI assist only)
    # ------------------------------------------------------------------
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for site in self:
            if site.partner_id:
                if not site.contact_name:
                    site.contact_name = site.partner_id.name
                if not site.contact_phone:
                    site.contact_phone = site.partner_id.phone
                if not site.contact_email:
                    site.contact_email = site.partner_id.email
                if not site.city:
                    site.city = site.partner_id.city
