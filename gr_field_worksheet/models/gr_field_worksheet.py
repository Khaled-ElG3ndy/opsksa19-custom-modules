# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrFieldWorksheet(models.Model):
    """The paperless Field Inspection Report. A technician fills this on a tablet;
    it can link to a maintenance job or a rental inspection. 'Verified' requires a
    layered evidence bundle (signature/PIN + optional scan/GPS/photos)."""
    _name = 'gr.field.worksheet'
    _description = 'Technician Field Worksheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Worksheet Ref', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)

    # --- link (to a job OR a rental inspection) ---
    job_id = fields.Many2one(
        'gr.maintenance.job', string='Maintenance Job', index=True, ondelete='cascade')
    inspection_id = fields.Many2one(
        'gr.rental.inspection', string='Rental Inspection', index=True, ondelete='cascade')

    # --- header (mirrors the paper form) ---
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Equipment (Asset No)', required=True, index=True)
    serial_number = fields.Char(
        related='asset_id.serial_number', store=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    contact_no = fields.Char(string='Contact No')
    project_name = fields.Char(string='Project Name')
    location = fields.Char(string='Location')
    hour_reading = fields.Float(string='Hour Reading')
    time_in = fields.Datetime(string='Time In')
    time_out = fields.Datetime(string='Time Out')

    visiting_mode = fields.Selection([
        ('customer_request', 'Customer Request'),
        ('cash', 'Cash'),
        ('free', 'Free'),
        ('service_repair', 'Service & Repair'),
        ('regular', 'Regular Visit & Inspection'),
    ], string='Visiting Mode', default='regular')

    # --- System Function Panel (the readings block) ---
    voltage_vac = fields.Float(string='Voltage (VAC)')
    frequency_hz = fields.Float(string='Frequency (HZ)')
    battery_voltage_dcv = fields.Float(string='Battery Voltage (DCV)')
    oil_pressure_kpa = fields.Float(string='Oil Pressure (KPA)')
    speed_rpm = fields.Float(string='Speed (RPM)')
    water_temp_c = fields.Float(string='Water Temp (C)')
    load_5m = fields.Float(string='Load @ 5 min')
    load_10m = fields.Float(string='Load @ 10 min')
    load_15m = fields.Float(string='Load @ 15 min')

    # --- checklist + spare parts + remarks ---
    checklist_ids = fields.One2many(
        'gr.field.worksheet.check', 'worksheet_id', string='Mechanical Checklist')
    spare_part_ids = fields.One2many(
        'gr.field.worksheet.part', 'worksheet_id', string='Spare Parts')
    remarks = fields.Text(string='Remarks')

    # --- VERIFIED PROOF: the evidence bundle ---
    technician_id = fields.Many2one(
        'res.users', string='Technician', default=lambda self: self.env.user)
    technician_signature = fields.Binary(string='Technician Signature', attachment=False)
    customer_ack_name = fields.Char(string='Customer Name (acknowledged)')
    customer_signature = fields.Binary(string='Customer Signature', attachment=False)
    verification_pin = fields.Char(
        string='Verification PIN', copy=False,
        help="Optional second factor: a PIN the customer or supervisor enters to "
             "confirm the work was physically completed.")
    scanned_serial = fields.Char(
        string='Scanned Serial',
        help="Serial scanned on site. Must match the equipment's serial to prove "
             "the right unit was serviced.")
    gps_latitude = fields.Float(string='GPS Latitude', digits=(10, 7))
    gps_longitude = fields.Float(string='GPS Longitude', digits=(10, 7))
    photo_ids = fields.Many2many(
        'ir.attachment', 'gr_worksheet_photo_rel', 'worksheet_id', 'attachment_id',
        string='Photos', domain=[('mimetype', 'like', 'image/')])
    photo_count = fields.Integer(
        compute='_compute_photo_count', string='Photo Count')

    verified = fields.Boolean(string='Verified', readonly=True, copy=False, tracking=True)
    verified_on = fields.Datetime(string='Verified On', readonly=True, copy=False)
    verified_by_id = fields.Many2one('res.users', string='Verified By', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('verified', 'Verified'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    # verification-requirement toggles (per-company policy, sensible defaults)
    require_customer_signature = fields.Boolean(
        string='Require Customer Signature', default=True)
    require_serial_scan = fields.Boolean(
        string='Require Serial Scan', default=True)
    require_gps = fields.Boolean(string='Require GPS', default=False)
    require_photo = fields.Boolean(string='Require Photo', default=False)

    serial_scan_ok = fields.Boolean(
        string='Serial Scan Matches', compute='_compute_serial_scan_ok', store=True)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The worksheet reference must be unique per company.",
    )

    def _compute_photo_count(self):
        for w in self:
            w.photo_count = len(w.photo_ids)

    @api.depends('scanned_serial', 'asset_id.serial_number')
    def _compute_serial_scan_ok(self):
        for w in self:
            if not w.scanned_serial or not w.asset_id.serial_number:
                w.serial_scan_ok = False
            else:
                w.serial_scan_ok = (
                    w.scanned_serial.strip().lower()
                    == w.asset_id.serial_number.strip().lower())

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.field.worksheet') or _('New')
        worksheets = super().create(vals_list)
        worksheets._populate_default_checklist()
        return worksheets

    @api.onchange('job_id')
    def _onchange_job(self):
        if self.job_id:
            self.asset_id = self.job_id.asset_id

    @api.onchange('inspection_id')
    def _onchange_inspection(self):
        if self.inspection_id:
            self.asset_id = self.inspection_id.asset_id
            self.partner_id = self.inspection_id.partner_id

    @api.constrains('job_id', 'inspection_id')
    def _check_one_link(self):
        for w in self:
            if w.job_id and w.inspection_id:
                raise UserError(_(
                    "Worksheet %s cannot link to both a maintenance job and a "
                    "rental inspection - choose one.") % w.name)

    def _populate_default_checklist(self):
        Item = self.env['gr.field.worksheet.check.item']
        for w in self:
            if not w.checklist_ids:
                items = Item.search([], order='sequence, id')
                w.checklist_ids = [(0, 0, {
                    'name': it.name, 'sequence': it.sequence}) for it in items]

    # ------------------------------------------------------------------
    def action_load_checklist(self):
        self._populate_default_checklist()
        return True

    def action_submit(self):
        for w in self:
            if w.state != 'draft':
                raise UserError(_("Only draft worksheets can be submitted."))
            w.state = 'submitted'
        return True

    def _verification_errors(self):
        """Return a list of unmet evidence requirements (empty = ready to verify)."""
        self.ensure_one()
        errs = []
        if not self.technician_signature:
            errs.append(_("technician signature"))
        if self.require_customer_signature and not self.customer_signature:
            errs.append(_("customer signature"))
        if not self.verification_pin and not self.customer_signature:
            errs.append(_("a PIN or a customer signature"))
        if self.require_serial_scan and not self.serial_scan_ok:
            errs.append(_("a matching serial scan"))
        if self.require_gps and not (self.gps_latitude and self.gps_longitude):
            errs.append(_("GPS coordinates"))
        if self.require_photo and not self.photo_ids:
            errs.append(_("at least one photo"))
        return errs

    def action_verify(self):
        for w in self:
            if w.state not in ('submitted', 'draft'):
                raise UserError(_("Only submitted worksheets can be verified."))
            errs = w._verification_errors()
            if errs:
                raise UserError(_(
                    "Worksheet %(ref)s cannot be verified yet. Missing proof: "
                    "%(items)s.", ref=w.name, items=', '.join(errs)))
            w.write({
                'verified': True,
                'verified_on': fields.Datetime.now(),
                'verified_by_id': self.env.user.id,
                'state': 'verified',
            })
            w.message_post(
                body=_("Worksheet verified - proof bundle complete."),
                subtype_xmlid='mail.mt_note')
        return True

    def action_cancel(self):
        for w in self:
            if w.state == 'verified':
                raise UserError(_(
                    "A verified worksheet cannot be cancelled (it is proof of "
                    "service). Ref %s.") % w.name)
            w.state = 'cancelled'
        return True

    def action_reset_draft(self):
        for w in self:
            if w.verified:
                raise UserError(_("A verified worksheet cannot be reset."))
            w.state = 'draft'
        return True


class GrFieldWorksheetCheck(models.Model):
    _name = 'gr.field.worksheet.check'
    _description = 'Field Worksheet Checklist Line'
    _order = 'worksheet_id, sequence, id'

    worksheet_id = fields.Many2one(
        'gr.field.worksheet', string='Worksheet', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Check Item', required=True)
    result = fields.Selection([
        ('ok', 'OK'),
        ('fail', 'Fail'),
        ('na', 'N/A'),
    ], string='Result', default='ok')
    note = fields.Char(string='Note')


class GrFieldWorksheetPart(models.Model):
    _name = 'gr.field.worksheet.part'
    _description = 'Field Worksheet Spare Part Line'
    _order = 'worksheet_id, sequence, id'

    worksheet_id = fields.Many2one(
        'gr.field.worksheet', string='Worksheet', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    part_number = fields.Char(string='Part Number')
    description = fields.Char(string='Description')
    quantity = fields.Float(string='Qty', default=1.0)
    remarks = fields.Char(string='Remarks')


class GrFieldWorksheetCheckItem(models.Model):
    """Master list of mechanical-checklist items (ABSAL's ~27-item form list)."""
    _name = 'gr.field.worksheet.check.item'
    _description = 'Field Worksheet Checklist Item (master)'
    _order = 'sequence, id'

    name = fields.Char(string='Check Item', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)


class GrMaintenanceJob(models.Model):
    _inherit = 'gr.maintenance.job'

    field_worksheet_ids = fields.One2many(
        'gr.field.worksheet', 'job_id', string='Field Worksheets')
    field_worksheet_count = fields.Integer(
        string='Field Worksheet Count',
        compute='_compute_field_worksheet_counts')
    verified_field_worksheet_count = fields.Integer(
        string='Verified Field Worksheets',
        compute='_compute_field_worksheet_counts')

    def _compute_field_worksheet_counts(self):
        for job in self:
            worksheets = job.field_worksheet_ids
            job.field_worksheet_count = len(worksheets)
            job.verified_field_worksheet_count = len(worksheets.filtered('verified'))

    def _field_worksheet_action(self, domain=None, res_id=False):
        action = self.env['ir.actions.act_window']._for_xml_id(
            'gr_field_worksheet.action_gr_field_worksheet')
        action.update({
            'domain': domain or [('job_id', 'in', self.ids)],
            'context': {
                'default_job_id': self[:1].id if self else False,
                'default_asset_id': self[:1].asset_id.id if self else False,
                'default_partner_id': (
                    self[:1].asset_id.owner_partner_id.id
                    if self and self[:1].asset_id.owner_type == 'customer_owned'
                    else False
                ),
                'default_technician_id': (
                    self[:1].technician_id.id if self and self[:1].technician_id
                    else self.env.user.id
                ),
                'default_hour_reading': (
                    self[:1].meter_at_service
                    or self[:1].asset_id.current_hour_meter
                    if self else 0.0
                ),
            },
        })
        if res_id:
            action.update({'views': [(False, 'form')], 'res_id': res_id})
        return action

    def action_create_field_worksheet(self):
        self.ensure_one()
        worksheet = self.env['gr.field.worksheet'].create({
            'job_id': self.id,
            'asset_id': self.asset_id.id,
            'partner_id': (
                self.asset_id.owner_partner_id.id
                if self.asset_id.owner_type == 'customer_owned'
                else False
            ),
            'technician_id': self.technician_id.id or self.env.user.id,
            'hour_reading': self.meter_at_service or self.asset_id.current_hour_meter,
            'time_in': fields.Datetime.now(),
        })
        return self._field_worksheet_action(res_id=worksheet.id)

    def action_view_field_worksheets(self):
        self.ensure_one()
        worksheets = self.field_worksheet_ids
        if len(worksheets) == 1:
            return self._field_worksheet_action(
                domain=[('job_id', '=', self.id)], res_id=worksheets.id)
        return self._field_worksheet_action(domain=[('job_id', '=', self.id)])
