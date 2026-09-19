# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GrEquipmentType(models.Model):
    _name = 'gr.equipment.type'
    _description = 'Equipment Type'
    _order = 'sequence, name'

    name = fields.Char(string='Asset Type', required=True, translate=True)
    code = fields.Char(string='Code', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    asset_ids = fields.One2many(
        'gr.generator.asset', 'equipment_type_id', string='Equipment')
    asset_count = fields.Integer(
        string='Equipment Count', compute='_compute_asset_count')
    rental_requires_dispatch = fields.Boolean(
        string='Requires Dispatch / Delivery', default=True,
        help="If enabled, rental orders for this equipment type go through "
             "the Dispatch step before rental can start.")
    rental_requires_installation = fields.Boolean(
        string='Requires Installation',
        help="If enabled, rental orders must be installed/commissioned before "
             "rental can start.")
    rental_requires_meter_readings = fields.Boolean(
        string='Requires Meter Readings',
        help="If enabled, start/end meter readings are shown and validated.")
    rental_requires_delivery_inspection = fields.Boolean(
        string='Requires Delivery Inspection',
        help="If enabled, dispatch is blocked until a delivery inspection is "
             "passed.")
    rental_requires_return_inspection = fields.Boolean(
        string='Requires Return Inspection',
        help="If enabled, closing is blocked until a return inspection is "
             "passed.")
    rental_requires_delivery_signature = fields.Boolean(
        string='Requires Delivery Signature',
        help="Controls whether delivery receiver/signature fields are shown.")
    rental_requires_return_signature = fields.Boolean(
        string='Requires Return Signature',
        help="Controls whether return signature fields are shown.")
    rental_standalone_ok = fields.Boolean(
        string='Can Be Rented Standalone', default=True,
        help="If enabled, this equipment type can be rented without a main "
             "asset.")
    rental_accessory_ok = fields.Boolean(
        string='Can Be Added as Accessory', default=True,
        help="If enabled, this equipment type can be added in the Assets & "
             "Accessories tab with another main asset.")

    _code_company_uniq = models.Constraint(
        'unique(code)',
        "The equipment type code must be unique.",
    )

    def _compute_asset_count(self):
        counts = dict.fromkeys(self.ids, 0)
        for equipment_type, count in self.env['gr.generator.asset']._read_group(
                [('equipment_type_id', 'in', self.ids)],
                ['equipment_type_id'], ['__count']):
            counts[equipment_type.id] = count
        for equipment_type in self:
            equipment_type.asset_count = counts.get(equipment_type.id, 0)

    def action_view_assets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Equipment - %s') % self.name,
            'res_model': 'gr.generator.asset',
            'view_mode': 'list,kanban,form,pivot',
            'domain': [('equipment_type_id', '=', self.id)],
            'context': {'default_equipment_type_id': self.id},
        }


class GrEquipment(models.Model):
    """Owner dimension on the equipment spine. Every physical generator is one
    equipment record; the owner type drives availability and money flow."""
    _inherit = 'gr.generator.asset'

    def _default_equipment_type_id(self):
        equipment_type = self.env.ref(
            'gr_equipment.equipment_type_generator', raise_if_not_found=False)
        if not equipment_type:
            equipment_type = self.env['gr.equipment.type'].search(
                [('code', '=', 'GEN')], limit=1)
        return equipment_type.id if equipment_type else False

    equipment_type_id = fields.Many2one(
        'gr.equipment.type', string='Asset Type', index=True, tracking=True,
        default=_default_equipment_type_id, ondelete='restrict',
        help="Classifies the physical asset: generator, cable, fuel tank, "
             "distribution panel, or any future rentable equipment type.")
    is_generator_type = fields.Boolean(
        string='Generator Type', compute='_compute_is_generator_type',
        store=True)
    specification = fields.Char(
        string='Technical Specification',
        help="General specification for non-generator equipment, such as "
             "4-core 120mm 50m, 1000 L, 400V, or panel size.")
    length_m = fields.Float(string='Length (m)')
    capacity = fields.Char(string='Capacity')
    size_label = fields.Char(string='Size')
    voltage_label = fields.Char(string='Voltage')
    dispatch_datetime = fields.Datetime(
        string='Dispatch Date', readonly=True, copy=False)

    current_presence_type = fields.Selection([
        ('customer', 'At Customer'),
        ('warehouse', 'In Warehouse'),
        ('maintenance', 'In Maintenance'),
        ('inspection', 'Under Inspection'),
        ('transit', 'In Transit'),
        ('reserved', 'Reserved'),
        ('unavailable', 'Unavailable'),
        ('available', 'Available'),
        ('out_of_service', 'Damaged / Out of Service'),
    ], string='Current Presence', compute='_compute_current_presence',
        store=True, readonly=True)
    availability_state = fields.Selection([
        ('available', 'Available'),
        ('rented', 'Rented / Reserved'),
        ('maintenance', 'In Maintenance'),
        ('unavailable', 'Unavailable'),
    ], string='Availability', compute='_compute_availability_state',
        store=True, readonly=True, index=True,
        help="Operational availability bucket used by the quick equipment "
             "availability screen. Rental-committed statuses are grouped as "
             "Rented / Reserved, while maintenance, breakdown, inspection and "
             "non-rentable units are kept out of the available pool.")
    current_rental_order_id = fields.Many2one(
        'gr.rental.order', string='Current Rental Order', readonly=True,
        copy=False)
    current_contract_id = fields.Many2one(
        'gr.rental.contract', string='Current Contract', readonly=True,
        copy=False)
    current_site_id = fields.Many2one(
        'gr.customer.site', string='Current Site', readonly=True, copy=False)
    current_location_label = fields.Char(
        string='Current Location', compute='_compute_current_presence',
        store=True, readonly=True)
    expected_return_datetime = fields.Datetime(
        string='Expected Return', readonly=True, copy=False)

    owner_type = fields.Selection([
        ('owned', 'Company Owned'),
        ('rented_in', 'Third-Party'),
        ('customer_owned', 'Customer-owned'),
    ], string='Ownership', required=True, default='owned', tracking=True, index=True,
        help="Company Owned: ABSAL's own rental fleet, a real company asset. "
             "Third-Party: NOT a company asset - rented in from a third-party "
             "supplier and re-rented to customers for the supplier's rental "
             "period only. Customer-owned: belongs to a customer ABSAL only "
             "services - never in the rental pool.")

    owner_partner_id = fields.Many2one(
        'res.partner', string='Owner / Supplier', tracking=True,
        help="For Third-Party units, the supplier ABSAL rents from and pays. "
             "For Customer-owned units, the customer who owns the generator. "
             "Empty for Company Owned units.")

    is_third_party = fields.Boolean(
        string='Third-Party Equipment', compute='_compute_is_third_party',
        store=True, index=True,
        help="True when the unit is rented in from a supplier and is NOT a "
             "company-owned asset. Drives the third-party badge, the separated "
             "menus, and the owned-fleet dashboard KPIs.")

    supplier_equipment_ref = fields.Char(
        string='Supplier Equipment Reference', tracking=True, copy=False,
        help="The supplier's own number/reference for this unit (e.g. "
             "ABC-GEN-55). Third-party equipment only - this is how the "
             "supplier identifies the unit, not an ABSAL asset code.")

    is_rentable = fields.Boolean(
        string='Rentable', compute='_compute_is_rentable', store=True,
        help="True for Company Owned and Third-Party units; False for "
             "Customer-owned units, which are serviced only and never enter "
             "the rental pool.")

    _WORKFLOW_OVERRIDE_SELECTION = [
        ('inherit', 'Use Equipment Type Setting'),
        ('yes', 'Yes'),
        ('no', 'No'),
    ]
    rental_requires_dispatch_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Dispatch / Delivery Override',
        default='inherit', required=True)
    rental_requires_installation_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Installation Override',
        default='inherit', required=True)
    rental_requires_meter_readings_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Meter Readings Override',
        default='inherit', required=True)
    rental_requires_delivery_inspection_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Delivery Inspection Override',
        default='inherit', required=True)
    rental_requires_return_inspection_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Return Inspection Override',
        default='inherit', required=True)
    rental_requires_delivery_signature_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Delivery Signature Override',
        default='inherit', required=True)
    rental_requires_return_signature_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Return Signature Override',
        default='inherit', required=True)
    rental_standalone_ok_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Standalone Rental Override',
        default='inherit', required=True)
    rental_accessory_ok_override = fields.Selection(
        _WORKFLOW_OVERRIDE_SELECTION, string='Accessory Rental Override',
        default='inherit', required=True)

    rental_requires_dispatch = fields.Boolean(
        string='Requires Dispatch / Delivery',
        compute='_compute_rental_workflow_flags', store=True)
    rental_requires_installation = fields.Boolean(
        string='Requires Installation',
        compute='_compute_rental_workflow_flags', store=True)
    rental_requires_meter_readings = fields.Boolean(
        string='Requires Meter Readings',
        compute='_compute_rental_workflow_flags', store=True)
    rental_requires_delivery_inspection = fields.Boolean(
        string='Requires Delivery Inspection',
        compute='_compute_rental_workflow_flags', store=True)
    rental_requires_return_inspection = fields.Boolean(
        string='Requires Return Inspection',
        compute='_compute_rental_workflow_flags', store=True)
    rental_requires_delivery_signature = fields.Boolean(
        string='Requires Delivery Signature',
        compute='_compute_rental_workflow_flags', store=True)
    rental_requires_return_signature = fields.Boolean(
        string='Requires Return Signature',
        compute='_compute_rental_workflow_flags', store=True)
    rental_standalone_ok = fields.Boolean(
        string='Can Be Rented Standalone',
        compute='_compute_rental_workflow_flags', store=True)
    rental_accessory_ok = fields.Boolean(
        string='Can Be Added as Accessory',
        compute='_compute_rental_workflow_flags', store=True)

    @api.depends('equipment_type_id.code')
    def _compute_is_generator_type(self):
        for eq in self:
            eq.is_generator_type = (eq.equipment_type_id.code or '') == 'GEN'

    @api.depends('status', 'current_customer_id', 'current_site_id',
                 'depot_location_id', 'current_rental_order_id')
    def _compute_current_presence(self):
        for asset in self:
            status = asset.status
            if status in ('on_rent', 'installed') and asset.current_customer_id:
                asset.current_presence_type = 'customer'
            elif status == 'reserved':
                asset.current_presence_type = 'reserved'
            elif status == 'in_transit':
                asset.current_presence_type = 'transit'
            elif status in ('under_maintenance', 'maintenance_due'):
                asset.current_presence_type = 'maintenance'
            elif status == 'returned_pending_inspection':
                asset.current_presence_type = 'inspection'
            elif status in ('breakdown', 'retired'):
                asset.current_presence_type = 'out_of_service'
            elif status == 'unavailable':
                asset.current_presence_type = 'unavailable'
            else:
                asset.current_presence_type = 'available'
            asset.current_location_label = (
                asset.current_site_id.display_name
                or asset.current_site_ref
                or asset.depot_location_id.display_name
                or asset.current_customer_id.display_name
                or False)

    @api.depends('status', 'is_rentable', 'maintenance_overdue')
    def _compute_availability_state(self):
        rental_committed_statuses = (
            'reserved', 'in_transit', 'installed', 'on_rent')
        maintenance_statuses = (
            'maintenance_due', 'under_maintenance', 'breakdown')
        unavailable_statuses = (
            'returned_pending_inspection', 'unavailable', 'retired')
        for asset in self:
            if not asset.is_rentable or asset.status in unavailable_statuses:
                asset.availability_state = 'unavailable'
            elif asset.status in maintenance_statuses or asset.maintenance_overdue:
                asset.availability_state = 'maintenance'
            elif asset.status in rental_committed_statuses:
                asset.availability_state = 'rented'
            else:
                asset.availability_state = 'available'

    @api.depends('owner_type')
    def _compute_is_rentable(self):
        for eq in self:
            eq.is_rentable = eq.owner_type in ('owned', 'rented_in')

    @api.depends('owner_type')
    def _compute_is_third_party(self):
        for eq in self:
            eq.is_third_party = eq.owner_type == 'rented_in'

    @api.depends('name')
    @api.depends_context('gr_show_ownership')
    def _compute_display_name(self):
        """Opt-in ownership suffix, so a third-party unit announces itself in
        every selection dropdown it appears in.

        Deliberately context-gated rather than unconditional: display_name is
        copied into stored fields (gr.rental.item.line.asset_display_name),
        printed on reports and quoted in error messages, so permanently
        rewriting it would rewrite records that are not about ownership. The
        pattern mirrors product.product's display_default_code."""
        super()._compute_display_name()
        if not self.env.context.get('gr_show_ownership'):
            return
        marker = _("Third-Party")
        for eq in self:
            if eq.owner_type == 'rented_in':
                eq.display_name = '%s — %s' % (eq.display_name, marker)

    def _workflow_value(self, override, inherited):
        if override == 'yes':
            return True
        if override == 'no':
            return False
        return bool(inherited)

    @api.depends(
        'equipment_type_id.rental_requires_dispatch',
        'equipment_type_id.rental_requires_installation',
        'equipment_type_id.rental_requires_meter_readings',
        'equipment_type_id.rental_requires_delivery_inspection',
        'equipment_type_id.rental_requires_return_inspection',
        'equipment_type_id.rental_requires_delivery_signature',
        'equipment_type_id.rental_requires_return_signature',
        'equipment_type_id.rental_standalone_ok',
        'equipment_type_id.rental_accessory_ok',
        'rental_requires_dispatch_override',
        'rental_requires_installation_override',
        'rental_requires_meter_readings_override',
        'rental_requires_delivery_inspection_override',
        'rental_requires_return_inspection_override',
        'rental_requires_delivery_signature_override',
        'rental_requires_return_signature_override',
        'rental_standalone_ok_override',
        'rental_accessory_ok_override',
    )
    def _compute_rental_workflow_flags(self):
        for asset in self:
            equipment_type = asset.equipment_type_id
            asset.rental_requires_dispatch = asset._workflow_value(
                asset.rental_requires_dispatch_override,
                equipment_type.rental_requires_dispatch)
            asset.rental_requires_installation = asset._workflow_value(
                asset.rental_requires_installation_override,
                equipment_type.rental_requires_installation)
            asset.rental_requires_meter_readings = asset._workflow_value(
                asset.rental_requires_meter_readings_override,
                equipment_type.rental_requires_meter_readings)
            asset.rental_requires_delivery_inspection = asset._workflow_value(
                asset.rental_requires_delivery_inspection_override,
                equipment_type.rental_requires_delivery_inspection)
            asset.rental_requires_return_inspection = asset._workflow_value(
                asset.rental_requires_return_inspection_override,
                equipment_type.rental_requires_return_inspection)
            asset.rental_requires_delivery_signature = asset._workflow_value(
                asset.rental_requires_delivery_signature_override,
                equipment_type.rental_requires_delivery_signature)
            asset.rental_requires_return_signature = asset._workflow_value(
                asset.rental_requires_return_signature_override,
                equipment_type.rental_requires_return_signature)
            asset.rental_standalone_ok = asset._workflow_value(
                asset.rental_standalone_ok_override,
                equipment_type.rental_standalone_ok)
            asset.rental_accessory_ok = asset._workflow_value(
                asset.rental_accessory_ok_override,
                equipment_type.rental_accessory_ok)

    @api.onchange('owner_type')
    def _onchange_owner_type(self):
        # Company-owned units have no external owner party, and no supplier
        # reference: the supplier block is meaningless for our own assets.
        if self.owner_type == 'owned':
            self.owner_partner_id = False
        if self.owner_type != 'rented_in':
            self.supplier_equipment_ref = False

    @api.constrains('owner_type', 'owner_partner_id')
    def _check_owner_partner(self):
        for eq in self:
            if eq.owner_type in ('rented_in', 'customer_owned') and not eq.owner_partner_id:
                raise ValidationError(_(
                    "Equipment %s is %s, so it must record an owner/supplier.")
                    % (eq.display_name,
                       dict(self._fields['owner_type'].selection)[eq.owner_type]))
            if eq.owner_type == 'owned' and eq.owner_partner_id:
                raise ValidationError(_(
                    "Company Owned equipment %s should not have an external "
                    "owner/supplier.") % eq.display_name)

    @api.constrains('owner_type', 'supplier_equipment_ref')
    def _check_supplier_equipment_ref(self):
        """A supplier's own unit reference only means something while we are
        renting the unit in. Keeping it on a company asset would suggest the
        asset belongs to somebody else."""
        for eq in self:
            if eq.supplier_equipment_ref and eq.owner_type != 'rented_in':
                raise ValidationError(_(
                    "Equipment %s is not Third-Party equipment, so it cannot "
                    "carry a supplier equipment reference.") % eq.display_name)

    @api.constrains('owner_type', 'status')
    def _check_customer_owned_not_rented(self):
        """Server-side guard: a customer-owned unit can never sit in a rental-
        related status. It is serviced only, never dispatched."""
        rental_statuses = ('reserved', 'in_transit', 'installed', 'on_rent',
                           'returned_pending_inspection')
        for eq in self:
            if eq.owner_type == 'customer_owned' and eq.status in rental_statuses:
                raise ValidationError(_(
                    "Equipment %s is Customer-owned and cannot be placed in a "
                    "rental status (%s). Customer-owned units are serviced only.")
                    % (eq.display_name, eq.status))
