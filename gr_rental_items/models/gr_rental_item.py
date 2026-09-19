# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrRentalItemType(models.Model):
    """The maintainable catalogue of rentable item TYPES.
    Seeded with cable / fuel tank / distribution panel; the client adds more
    from the UI without any code change."""
    _name = 'gr.rental.item.type'
    _description = 'Rentable Item Type'
    _order = 'sequence, name'

    name = fields.Char(string='Item Type', required=True, translate=True)
    code = fields.Char(string='Code', help="Short code, e.g. CBL, TNK, PNL.")
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Description')
    default_daily_rate = fields.Monetary(
        string='Default Daily Rate', currency_field='currency_id',
        help="Suggested rate when this item is added to an order. Can be "
             "overridden per line, or set to zero / marked Free.")
    default_is_free_with_generator = fields.Boolean(
        string='Free with Generator by Default',
        help="If set, when this item is added to an order that also has a "
             "generator, the line defaults to Free.")
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    unit_ids = fields.One2many(
        'gr.rental.item.unit', 'item_type_id', string='Units')
    unit_count = fields.Integer(compute='_compute_unit_count', string='Units')

    def _compute_unit_count(self):
        for t in self:
            t.unit_count = len(t.unit_ids)

    def action_view_units(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Units — %s') % self.name,
            'res_model': 'gr.rental.item.unit',
            'domain': [('item_type_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_item_type_id': self.id},
        }


class GrRentalItemUnit(models.Model):
    """An individual physical unit of a rentable item (this cable, that tank).
    Tracked so it cannot be double-booked, mirroring how generators work."""
    _name = 'gr.rental.item.unit'
    _description = 'Rentable Item Unit'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(
        string='Item No', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    item_type_id = fields.Many2one(
        'gr.rental.item.type', string='Item Type', required=True, index=True,
        tracking=True, ondelete='restrict')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    serial_number = fields.Char(string='Serial Number', tracking=True)
    specification = fields.Char(
        string='Specification',
        help="e.g. '4-core 120mm 50m' for a cable, '1000 L' for a tank.")
    notes = fields.Text(string='Notes')

    status = fields.Selection([
        ('available', 'Available'),
        ('on_rent', 'On Rent'),
        ('maintenance', 'Under Maintenance'),
        ('unavailable', 'Unavailable'),
        ('retired', 'Retired'),
    ], string='Status', default='available', required=True, tracking=True, index=True)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The item number must be unique per company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.rental.item.unit') or _('New')
        return super().create(vals_list)

    @api.depends('name', 'item_type_id.name')
    def _compute_display_name(self):
        for u in self:
            if u.item_type_id:
                u.display_name = '%s [%s]' % (u.name, u.item_type_id.name)
            else:
                u.display_name = u.name


class GrGeneratorAssetRentalPricing(models.Model):
    _inherit = 'gr.generator.asset'

    rental_daily_rate = fields.Monetary(
        string='Rental Daily Rate', currency_field='currency_id',
        help="Default daily rental rate when this asset is added as a rental "
             "order line. The line can still override the rate.")
    default_is_free_with_asset = fields.Boolean(
        string='Free with Another Asset by Default',
        help="If set, this asset defaults to a free line when the same order "
             "already rents another asset, such as a generator.")


class GrRentalOrderLine(models.Model):
    """An item line on a rental order. Each line is one physical item unit,
    with its OWN price - or FREE (bundled with the generator)."""
    _name = 'gr.rental.order.line'
    _description = 'Rental Order Item Line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    company_id = fields.Many2one(
        related='order_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)

    equipment_asset_id = fields.Many2one(
        'gr.generator.asset', string='Rented Serial', index=True,
        domain="[('status', '=', 'available')]",
        help="Select the physical rented serial for this line. Add one line "
             "per generator, cable, fuel tank, panel, or any future tracked "
             "rental asset.")
    is_primary_asset_line = fields.Boolean(
        string='Primary Rental Serial',
        help="Technical marker for the first rental asset synced to legacy "
             "main-asset fields. Users still enter all serials in the same "
             "rental lines list.")
    item_type_id = fields.Many2one(
        'gr.rental.item.type', string='Item Type')
    item_unit_id = fields.Many2one(
        'gr.rental.item.unit', string='Legacy Item Unit', index=True,
        domain="[('item_type_id', '=', item_type_id), "
               "('status', 'in', ['available', 'on_rent'])]",
        help="Backward-compatible rentable item unit. New asset rentals should "
             "use Asset instead.")
    specification = fields.Char(
        string='Specification', compute='_compute_line_asset_labels',
        readonly=True)
    asset_type_display_name = fields.Char(
        string='Asset Type', compute='_compute_line_asset_labels',
        readonly=True)
    asset_display_name = fields.Char(
        string='Display Name', compute='_compute_line_asset_labels',
        readonly=True)
    asset_serial_number = fields.Char(
        string='Serial Number', compute='_compute_line_asset_labels',
        readonly=True)

    is_free = fields.Boolean(
        string='Free of Charge',
        help="Tick if this item goes out at no charge (bundled with the "
             "main asset). The line then bills nothing.")
    daily_rate = fields.Monetary(
        string='Daily Rate', currency_field='currency_id',
        help="Rate for this item, independent of the generator's rate.")
    quantity_days = fields.Float(
        string='Days', default=1.0,
        help="Rental days for this item (may differ from the generator's).")
    line_total = fields.Monetary(
        string='Line Total', currency_field='currency_id',
        compute='_compute_line_total', store=True)

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS gr_rental_order_line_asset_avail_idx
                ON gr_rental_order_line (equipment_asset_id, order_id)
             WHERE equipment_asset_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS gr_rental_order_line_item_avail_idx
                ON gr_rental_order_line (item_unit_id, order_id)
             WHERE item_unit_id IS NOT NULL
        """)

    @api.depends('is_free', 'daily_rate', 'quantity_days')
    def _compute_line_total(self):
        for l in self:
            l.line_total = 0.0 if l.is_free else (l.daily_rate or 0.0) * (l.quantity_days or 0.0)

    @api.depends('equipment_asset_id', 'item_unit_id', 'item_type_id')
    def _compute_line_asset_labels(self):
        for line in self:
            asset = line.equipment_asset_id
            unit = line.item_unit_id
            if asset:
                line.specification = asset.specification
                line.asset_type_display_name = asset.equipment_type_id.display_name
                line.asset_display_name = asset.display_name
                line.asset_serial_number = asset.serial_number
            elif unit:
                line.specification = unit.specification
                line.asset_type_display_name = unit.item_type_id.display_name
                line.asset_display_name = unit.display_name
                line.asset_serial_number = unit.serial_number
            else:
                line.specification = False
                line.asset_type_display_name = line.item_type_id.display_name
                line.asset_display_name = False
                line.asset_serial_number = False

    def _order_has_other_asset(self):
        self.ensure_one()
        order = self.order_id
        return bool(
            (order.asset_id and order.asset_id != self.equipment_asset_id)
            or order.item_line_ids.filtered(
                lambda l: l.id != self.id
                and (l.equipment_asset_id or l.item_unit_id)))

    def _asset_is_generator(self, asset):
        return bool(
            asset
            and (
                'is_generator_type' not in asset._fields
                or asset.is_generator_type))

    def _order_has_generator_serial(self):
        self.ensure_one()
        order = self.order_id
        if self._asset_is_generator(order.asset_id):
            return True
        return bool(order.item_line_ids.filtered(
            lambda l: l.id != self.id
            and self._asset_is_generator(l.equipment_asset_id)))

    def _default_item_type_for_equipment(self, asset):
        if not asset or not asset.equipment_type_id:
            return False
        return self.env['gr.rental.item.type'].search([
            ('code', '=', asset.equipment_type_id.code),
            '|', ('company_id', '=', asset.company_id.id),
                 ('company_id', '=', False),
        ], limit=1)

    def _apply_equipment_asset_defaults(self):
        for line in self.filtered('equipment_asset_id'):
            asset = line.equipment_asset_id
            if not line.item_type_id:
                line.item_type_id = line._default_item_type_for_equipment(asset)
            if not line.daily_rate:
                line.daily_rate = asset.rental_daily_rate
            if (asset.default_is_free_with_asset
                    and line._order_has_other_asset()):
                line.is_free = True

    @api.onchange('item_type_id')
    def _onchange_item_type(self):
        """Default the rate (and free flag) from the item type."""
        self.item_unit_id = False
        if self.item_type_id:
            self.daily_rate = self.item_type_id.default_daily_rate
            # only default to free if the order actually has a generator serial
            has_gen = self._order_has_generator_serial()
            self.is_free = bool(
                self.item_type_id.default_is_free_with_generator and has_gen)

    @api.onchange('equipment_asset_id')
    def _onchange_equipment_asset_id(self):
        self.item_unit_id = False
        self._apply_equipment_asset_defaults()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._apply_equipment_asset_defaults()
        if not self.env.context.get('gr_skip_primary_asset_sync'):
            lines.mapped('order_id')._sync_primary_asset_from_lines()
        lines._validate_order_availability_after_target_change()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if 'equipment_asset_id' in vals:
            self._apply_equipment_asset_defaults()
        if (
            not self.env.context.get('gr_skip_primary_asset_sync')
            and {'equipment_asset_id', 'item_unit_id', 'order_id'}
            & set(vals)
        ):
            self.mapped('order_id')._sync_primary_asset_from_lines()
        if {'equipment_asset_id', 'item_unit_id', 'order_id'} & set(vals):
            self._validate_order_availability_after_target_change()
        return res

    def unlink(self):
        orders = self.mapped('order_id')
        res = super().unlink()
        if not self.env.context.get('gr_skip_primary_asset_sync'):
            orders._sync_primary_asset_from_lines()
        return res

    # NOTE: the no-double-booking check lives on the ORDER (in action_reserve),
    # not here. A line-level @api.constrains cannot see the conflict at create
    # time because the new order is still in 'draft' - the clash only becomes
    # real when the order is reserved. See gr_rental_order_items.py.

    def _validate_order_availability_after_target_change(self):
        if self.env.context.get('gr_skip_availability_validation'):
            return True
        orders = self.mapped('order_id').filtered(
            lambda order: order.state in order._availability_commit_states())
        for order in orders:
            if order._availability_engine().order_has_physical_targets(order):
                order._check_order_availability(lock=False, exception='validation')
        return True

    @api.constrains('is_free', 'daily_rate')
    def _check_free_or_priced(self):
        for l in self:
            if not l.is_free and (l.daily_rate or 0.0) < 0:
                raise ValidationError(_("Daily rate cannot be negative."))

    @api.constrains('equipment_asset_id', 'item_unit_id')
    def _check_one_physical_target(self):
        for line in self:
            if bool(line.equipment_asset_id) == bool(line.item_unit_id):
                raise ValidationError(_(
                    "Each rental line must reference exactly one physical "
                    "asset: either an Asset or a legacy Item Unit."))
            if line.equipment_asset_id and \
                    line.equipment_asset_id == line.order_id.asset_id:
                if line.is_primary_asset_line:
                    continue
                raise ValidationError(_(
                    "Asset %s is already the main equipment on this order. "
                    "Do not add the same asset again as a line.")
                    % line.equipment_asset_id.display_name)

    @api.constrains('equipment_asset_id')
    def _check_equipment_asset_is_rentable(self):
        for line in self.filtered('equipment_asset_id'):
            if not line.equipment_asset_id.is_rentable:
                raise ValidationError(_(
                    "Asset %s is not rentable and cannot be added to a rental "
                    "order line.") % line.equipment_asset_id.display_name)
            if line.order_id.asset_id:
                if line.equipment_asset_id == line.order_id.asset_id:
                    continue
                if (not line.equipment_asset_id.rental_accessory_ok
                        and not line._asset_is_generator(line.equipment_asset_id)):
                    raise ValidationError(_(
                        "Asset %s cannot be added as an accessory with another "
                        "asset.") % line.equipment_asset_id.display_name)
            elif not line.equipment_asset_id.rental_standalone_ok:
                raise ValidationError(_(
                    "Asset %s cannot be rented standalone.")
                    % line.equipment_asset_id.display_name)
