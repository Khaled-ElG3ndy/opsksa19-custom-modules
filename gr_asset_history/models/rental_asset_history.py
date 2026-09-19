# -*- coding: utf-8 -*-
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


def history_text(env, text, **kwargs):
    """Interpolate an already-translated history line.

    `text` arrives translated (the call sites wrap it in ``_()``), so this only
    decides how the interpolated VALUES are rendered: in a right-to-left
    language they are isolated so a mixed Arabic/Latin row stays readable. The
    test is the active language's own direction rather than "is it Arabic",
    so any RTL language added later behaves the same.
    """
    if not kwargs:
        return text
    if not _history_is_rtl(env):
        return text % kwargs
    return text % {
        key: _history_rtl_value(value) for key, value in kwargs.items()
    }


def _history_is_rtl(env):
    # _get_data yields a dummy whose fields are all False for an unknown or
    # inactive code, so no extra guard is needed.
    return env['res.lang']._get_data(code=env.lang or '').direction == 'rtl'


def _history_rtl_value(value):
    if value in (False, None):
        value = ''
    text = str(value)
    # Keep mixed Arabic/English values stable in RTL list rows.
    return '«\u200e%s\u200e»' % text


class RentalAssetHistory(models.Model):
    _name = 'rental.asset.history'
    _description = 'Rental Asset History'
    _order = 'event_datetime desc, id desc'
    _rec_name = 'name'

    asset_id = fields.Many2one(
        'gr.generator.asset', string='Asset', index=True, ondelete='cascade')
    item_unit_id = fields.Many2one(
        'gr.rental.item.unit', string='Rentable Item', index=True,
        ondelete='cascade')
    event_datetime = fields.Datetime(
        string='Date & Time', required=True, index=True,
        default=fields.Datetime.now)
    event_type = fields.Selection([
        ('asset_created', 'Asset Created'),
        ('asset_updated', 'Asset Updated'),
        ('status_changed', 'Status Changed'),
        ('rental_order_created', 'Rental Order Created'),
        ('rental_confirmed', 'Rental Confirmed'),
        ('asset_reserved', 'Asset Reserved'),
        ('reservation_cancelled', 'Reservation Cancelled'),
        ('delivery', 'Delivered to Customer'),
        ('installed', 'Installed at Site'),
        ('rental_started', 'Rental Started'),
        ('off_hire_requested', 'Off-Hire Requested'),
        ('rental_extended', 'Rental Extended'),
        ('return', 'Returned from Customer'),
        ('inspection_started', 'Return Inspection Started'),
        ('rental_closed', 'Rental Closed'),
        ('cancelled', 'Cancelled'),
        ('contract_approved', 'Contract Approved'),
        ('contract_activated', 'Contract Activated'),
        ('maintenance_opened', 'Maintenance Opened'),
        ('maintenance_scheduled', 'Maintenance Scheduled'),
        ('maintenance_started', 'Maintenance Started'),
        ('maintenance_done', 'Maintenance Done'),
        ('maintenance_cancelled', 'Maintenance Cancelled'),
        ('inspection_created', 'Inspection Created'),
        ('inspection_passed', 'Inspection Passed'),
        ('inspection_failed', 'Inspection Failed'),
        ('damage_found', 'Damage Found'),
        ('visit_created', 'Visit / Worksheet Created'),
        ('visit_submitted', 'Visit / Worksheet Submitted'),
        ('visit_verified', 'Visit / Worksheet Verified'),
        ('parts_used', 'Parts Used'),
        ('sublet_created', 'Rent-in Agreement Created'),
        ('sublet_direct_cost', 'Sublet Direct Cost'),
        ('vendor_received', 'Received / Committed from Vendor'),
        ('vendor_returned', 'Returned to Vendor'),
        ('vendor_cancelled', 'Vendor Rent-in Cancelled'),
        ('breakdown_reported', 'Breakdown Reported'),
        ('asset_retired', 'Asset Retired'),
        ('asset_reactivated', 'Asset Reactivated'),
        ('manual_note', 'Manual Note'),
    ], string='Event Type', required=True, index=True, default='manual_note')
    name = fields.Char(string='Details', required=True)
    description = fields.Text(string='Description')
    old_state = fields.Char(string='Previous State')
    new_state = fields.Char(string='New State')
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 index=True)
    previous_location_id = fields.Many2one(
        'gr.customer.site', string='Previous Site', index=True)
    location_id = fields.Many2one(
        'gr.customer.site', string='New Site', index=True)
    previous_location_label = fields.Char(string='Previous Location')
    location_label = fields.Char(string='Location')

    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', index=True)
    contract_id = fields.Many2one(
        'gr.rental.contract', string='Contract', index=True)
    maintenance_id = fields.Many2one(
        'gr.maintenance.job', string='Maintenance Job', index=True)
    inspection_id = fields.Many2one(
        'gr.rental.inspection', string='Inspection', index=True)
    visit_id = fields.Many2one(
        'gr.field.worksheet', string='Visit / Worksheet', index=True)
    picking_id = fields.Many2one('stock.picking', string='Stock Picking')
    parts_line_id = fields.Many2one(
        'gr.parts.consumption.line', string='Parts Consumption Line')
    sublet_agreement_id = fields.Many2one(
        'gr.sublet.agreement', string='Sublet Agreement')
    sublet_direct_cost_id = fields.Many2one(
        'gr.sublet.direct.cost', string='Sublet Direct Cost')

    source_model = fields.Char(string='Source Model', index=True, readonly=True)
    source_res_id = fields.Integer(string='Source ID', index=True, readonly=True)
    source_reference = fields.Char(string='Source Reference', readonly=True)
    technical_key = fields.Char(
        string='Technical Key', required=True, copy=False, index=True,
        default=lambda self: uuid.uuid4().hex,
        help="Deterministic key for automatic events. Prevents duplicate events "
             "when the same workflow step is retried.")
    is_automatic = fields.Boolean(string='Automatic Event', default=False)
    is_technical_event = fields.Boolean(
        string='Technical Event', compute='_compute_is_technical_event',
        store=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='Responsible User', required=True, index=True,
        default=lambda self: self.env.user)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    _technical_key_company_uniq = models.Constraint(
        'unique(technical_key, company_id)',
        "This asset-history event already exists for this company.",
    )

    @api.depends('event_type', 'description', 'source_model')
    def _compute_is_technical_event(self):
        for rec in self:
            rec.is_technical_event = rec._is_technical_history_event()

    def _is_technical_history_event(self):
        self.ensure_one()
        if self.event_type == 'status_changed':
            return True
        if self.event_type != 'asset_updated':
            return False
        routine_labels = self._technical_update_labels()
        if not routine_labels or not self.description:
            return False
        lines = [
            line.strip() for line in self.description.splitlines()
            if line.strip()
        ]
        return bool(lines) and all(
            line.split(':', 1)[0].strip() in routine_labels
            for line in lines
        )

    def _technical_update_labels(self):
        labels = set()
        model_names = []
        if self.asset_id:
            model_names.append('gr.generator.asset')
        if self.item_unit_id:
            model_names.append('gr.rental.item.unit')
        if self.source_model in ('gr.generator.asset', 'gr.rental.item.unit'):
            model_names.append(self.source_model)
        technical_fields = {
            'gr.generator.asset': {
                'status', 'current_customer_id', 'current_site_ref',
                'current_contract_ref', 'current_rental_order_ref',
            },
            'gr.rental.item.unit': {'status'},
        }
        for model_name in model_names:
            model = self.env[model_name]
            for field_name in technical_fields.get(model_name, set()):
                if field_name in model._fields:
                    labels.add(model._fields[field_name].string)
        return labels

    @api.constrains('asset_id', 'item_unit_id')
    def _check_one_target(self):
        for rec in self:
            if bool(rec.asset_id) == bool(rec.item_unit_id):
                raise ValidationError(_(
                    "History must be linked to exactly one generator asset or "
                    "one rentable item unit."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            asset = self.env['gr.generator.asset'].browse(vals.get('asset_id'))
            item = self.env['gr.rental.item.unit'].browse(vals.get('item_unit_id'))
            source = self._history_source_from_vals(vals)
            if not vals.get('company_id'):
                vals['company_id'] = (
                    asset.company_id.id if asset else
                    item.company_id.id if item else
                    source.company_id.id if source and 'company_id' in source._fields else
                    self.env.company.id)
            if not vals.get('user_id'):
                vals['user_id'] = self.env.user.id
            if not vals.get('source_reference') and source:
                vals['source_reference'] = source.display_name
        records = super().create(vals_list)
        records._touch_history_targets()
        return records

    def write(self, vals):
        protected = {'technical_key', 'event_datetime', 'source_model',
                     'source_res_id'}
        if protected & set(vals) and not self.env.user.has_group(
                'gr_security_base.group_generator_administrator'):
            raise UserError(_(
                "Only a Generator Administrator can change event date or source "
                "metadata."))
        return super().write(vals)

    def unlink(self):
        if self.filtered('is_automatic') and not self.env.user.has_group(
                'gr_security_base.group_generator_administrator'):
            raise UserError(_(
                "Automatic history events cannot be deleted by regular users."))
        return super().unlink()

    @api.model
    def _history_source_from_vals(self, vals):
        model_name = vals.get('source_model')
        res_id = vals.get('source_res_id')
        if not model_name or not res_id or model_name not in self.env:
            return self.env['ir.model']
        return self.env[model_name].browse(res_id).exists()

    def _touch_history_targets(self):
        for rec in self:
            vals = {'history_last_event_datetime': rec.event_datetime}
            if rec.asset_id and 'history_last_event_datetime' in rec.asset_id._fields:
                rec.asset_id.with_context(gr_skip_history_asset_write=True).write(vals)
            if rec.item_unit_id and \
                    'history_last_event_datetime' in rec.item_unit_id._fields:
                rec.item_unit_id.with_context(gr_skip_history_item_write=True).write(vals)

    @api.model
    def record_event(self, target, event_type, name, technical_key,
                     source=None, description=False, old_state=False,
                     new_state=False, partner=False, previous_location=False,
                     location=False, previous_location_label=False,
                     location_label=False, notes=False, event_datetime=False,
                     extra_vals=None):
        """Create one idempotent event for a generator asset or item unit."""
        if not target:
            return self.browse()
        target.ensure_one()
        company = target.company_id
        existing = self.search([
            ('technical_key', '=', technical_key),
            ('company_id', '=', company.id),
        ], limit=1)
        if existing:
            return existing
        vals = {
            'event_type': event_type,
            'name': name,
            'description': description,
            'old_state': old_state,
            'new_state': new_state,
            'partner_id': partner.id if partner else False,
            'previous_location_id': previous_location.id if previous_location else False,
            'location_id': location.id if location else False,
            'previous_location_label': previous_location_label,
            'location_label': location_label,
            'technical_key': technical_key,
            'is_automatic': True,
            'event_datetime': event_datetime or fields.Datetime.now(),
            'company_id': company.id,
            'notes': notes,
        }
        if target._name == 'gr.generator.asset':
            vals['asset_id'] = target.id
        elif target._name == 'gr.rental.item.unit':
            vals['item_unit_id'] = target.id
        else:
            raise ValidationError(_("Unsupported history target: %s") % target._name)
        if source:
            vals.update({
                'source_model': source._name,
                'source_res_id': source.id,
                'source_reference': source.display_name,
            })
            vals.update(self._source_link_values(source))
        if extra_vals:
            vals.update(extra_vals)
        return self.create(vals)

    def _source_link_values(self, source):
        vals = {}
        mapping = {
            'gr.rental.order': 'rental_order_id',
            'gr.rental.contract': 'contract_id',
            'gr.maintenance.job': 'maintenance_id',
            'gr.rental.inspection': 'inspection_id',
            'gr.field.worksheet': 'visit_id',
            'gr.parts.consumption.line': 'parts_line_id',
            'gr.sublet.agreement': 'sublet_agreement_id',
            'gr.sublet.direct.cost': 'sublet_direct_cost_id',
            'stock.picking': 'picking_id',
        }
        field_name = mapping.get(source._name)
        if field_name:
            vals[field_name] = source.id
        if source._name == 'gr.rental.order':
            vals['contract_id'] = source.contract_id.id
            vals['rental_order_id'] = source.id
        elif source._name == 'gr.maintenance.job':
            vals['maintenance_id'] = source.id
        elif source._name == 'gr.rental.inspection':
            vals['inspection_id'] = source.id
            vals['rental_order_id'] = source.rental_order_id.id
            vals['contract_id'] = source.rental_order_id.contract_id.id
        elif source._name == 'gr.field.worksheet':
            vals['visit_id'] = source.id
            vals['maintenance_id'] = source.job_id.id
            vals['inspection_id'] = source.inspection_id.id
        elif source._name == 'gr.parts.consumption.line':
            vals['parts_line_id'] = source.id
            vals['maintenance_id'] = source.job_id.id
        elif source._name == 'gr.sublet.agreement':
            vals['sublet_agreement_id'] = source.id
        elif source._name == 'gr.sublet.direct.cost':
            vals['sublet_direct_cost_id'] = source.id
            vals['sublet_agreement_id'] = source.agreement_id.id
            vals['rental_order_id'] = source.rental_order_id.id
        return vals

    def action_open_source(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            raise UserError(_("This history event has no source document."))
        if self.source_model not in self.env:
            raise UserError(_("Source model %s is not available.") % self.source_model)
        source = self.env[self.source_model].browse(self.source_res_id).exists()
        if not source:
            raise UserError(_("The source document no longer exists."))
        return {
            'type': 'ir.actions.act_window',
            'name': self.source_reference or source.display_name,
            'res_model': self.source_model,
            'res_id': source.id,
            'view_mode': 'form',
            'target': 'current',
        }
