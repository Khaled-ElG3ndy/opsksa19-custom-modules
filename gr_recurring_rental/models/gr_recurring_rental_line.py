# -*- coding: utf-8 -*-
"""What the customer normally takes.

A template line states a REQUIREMENT ("a 500 kVA generator"), not a promise of
one specific machine. The physical serial is chosen when the order is prepared,
and only if it is genuinely usable that day. A preferred unit is a hint, never
a guarantee: it may be out on another rental, in maintenance, or - for
third-party equipment - outside the window the supplier has given us.
"""
from odoo import api, fields, models, _


class GrRecurringRentalLine(models.Model):
    _name = 'gr.recurring.rental.line'
    _description = 'Recurring Rental Item'
    _order = 'recurring_id, sequence, id'

    recurring_id = fields.Many2one(
        'gr.recurring.rental', string='Recurring Rental', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    company_id = fields.Many2one(
        related='recurring_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)

    equipment_type_id = fields.Many2one(
        'gr.equipment.type', string='Equipment Type', index=True,
        help="What kind of unit the customer needs: generator, cable, fuel "
             "tank, distribution panel. This is the requirement that survives "
             "from month to month.")
    item_type_id = fields.Many2one(
        'gr.rental.item.type', string='Item Type',
        help="Catalogue item type, used for pricing defaults and for items "
             "that are not tracked as equipment assets.")
    required_kva = fields.Float(
        string='Required kVA',
        help="Capacity the customer needs, for generator lines. Recorded so "
             "the operator can pick an equivalent machine when the preferred "
             "one is unavailable.")
    specification = fields.Char(
        string='Specification',
        help="Free text for non-generator requirements, such as "
             "'4-core 120mm 50m'.")
    quantity = fields.Integer(
        string='Quantity', default=1, required=True,
        help="How many units of this requirement. Each unit becomes its own "
             "rental order line, because each is a separate serial.")

    preferred_asset_id = fields.Many2one(
        'gr.generator.asset', string='Preferred Unit',
        domain="[('is_rentable', '=', True)]",
        help="Optional. Used only when it is genuinely available on the rental "
             "dates and, for third-party units, covered by a valid supplier "
             "agreement. Otherwise the line is prepared without a serial for "
             "the operator to choose.")
    preferred_owner_type = fields.Selection(
        related='preferred_asset_id.owner_type', string='Preferred Unit Ownership',
        readonly=True)

    is_free = fields.Boolean(
        string='Free of Charge',
        help="Bundled at no charge, the way a cable often goes out free with "
             "a generator.")
    daily_rate_override = fields.Monetary(
        string='Agreed Daily Rate', currency_field='currency_id',
        help="Leave empty to price from the current catalogue and contract "
             "when the order is prepared - which is normally what you want, "
             "so a price change reaches next month's order. Fill it in only "
             "for a rate negotiated specifically for this arrangement.")
    notes = fields.Char(string='Notes')

    @api.depends('equipment_type_id', 'item_type_id', 'specification',
                 'required_kva')
    def _compute_display_name(self):
        for line in self:
            label = (line.equipment_type_id.display_name
                     or line.item_type_id.display_name
                     or _('Item'))
            detail = line.specification or (
                _('%s kVA') % int(line.required_kva) if line.required_kva else '')
            line.display_name = '%s %s' % (label, detail) if detail else label

    @api.onchange('equipment_type_id')
    def _onchange_equipment_type_id(self):
        """Point at the matching catalogue type so pricing defaults line up."""
        if not self.equipment_type_id:
            return
        if not self.item_type_id:
            self.item_type_id = self.env['gr.rental.item.type'].search([
                ('code', '=', self.equipment_type_id.code),
                '|', ('company_id', '=', self.company_id.id),
                     ('company_id', '=', False),
            ], limit=1)

    @api.onchange('preferred_asset_id')
    def _onchange_preferred_asset_id(self):
        asset = self.preferred_asset_id
        if not asset:
            return
        if not self.equipment_type_id:
            self.equipment_type_id = asset.equipment_type_id
        if not self.required_kva and asset.kva_rating:
            self.required_kva = asset.kva_rating

    # ------------------------------------------------------------------
    # Preferred-unit resolution
    # ------------------------------------------------------------------
    def _resolve_preferred_asset(self, start, end):
        """(asset, reason) - the unit to pre-fill, or why it was left out.

        Deliberately conservative. Every reason to refuse here mirrors a rule
        the rental order enforces later; pre-filling a unit that would fail
        those rules would only move the error to a worse moment.
        """
        self.ensure_one()
        asset = self.preferred_asset_id
        if not asset:
            if self.quantity:
                return asset, _(
                    "%(item)s x%(qty)s: select the unit(s) to rent.",
                    item=self.display_name, qty=self.quantity)
            return asset, False

        def refuse(detail):
            return self.env['gr.generator.asset'], _(
                "%(item)s: preferred unit %(asset)s not used - %(why)s",
                item=self.display_name, asset=asset.display_name, why=detail)

        if not asset.is_rentable:
            return refuse(_("it is customer-owned and never rented out."))
        if not asset.rental_standalone_ok and not asset.rental_accessory_ok:
            return refuse(_("its rental settings do not allow it to be rented."))
        engine = self.env['gr.rental.availability']
        conflicts = engine.conflicts_for_targets(
            asset,
            fields.Datetime.to_datetime(start),
            fields.Datetime.to_datetime(end),
            self.company_id,
        )
        if conflicts:
            return refuse(conflicts[0]['message'])
        return asset, False

    # ------------------------------------------------------------------
    # Order line values
    # ------------------------------------------------------------------
    def _order_line_vals(self, duration_days):
        """One rental order line's worth of values.

        Pricing is left to the order wherever possible: an empty rate lets
        gr.rental.order.line fill it from the asset or the catalogue at
        preparation time, so this month's order carries this month's prices.
        Only an explicitly agreed rate is copied as an override.
        """
        self.ensure_one()
        vals = {
            'item_type_id': self.item_type_id.id,
            'quantity_days': duration_days,
            'is_free': self.is_free,
        }
        if self.daily_rate_override:
            vals['daily_rate'] = self.daily_rate_override
        elif self.item_type_id and self.item_type_id.default_daily_rate:
            # create() does not fire onchanges, so the catalogue default is
            # applied here for item-type lines. Asset lines are handled by
            # gr.rental.order.line._apply_equipment_asset_defaults().
            vals['daily_rate'] = self.item_type_id.default_daily_rate
        return vals


class GrRecurringRentalOccurrence(models.Model):
    """One handled occurrence: prepared or skipped.

    This log is what makes preparation idempotent and skipping traceable. The
    unique constraint is the real duplicate guard - even if somebody edits the
    next rental date back to a month already dealt with, the same occurrence
    cannot be prepared twice.
    """
    _name = 'gr.recurring.rental.occurrence'
    _description = 'Recurring Rental Occurrence'
    _order = 'occurrence_date desc, id desc'

    recurring_id = fields.Many2one(
        'gr.recurring.rental', string='Recurring Rental', required=True,
        ondelete='cascade', index=True)
    occurrence_date = fields.Date(
        string='Occurrence Date', required=True, index=True)
    state = fields.Selection([
        ('prepared', 'Prepared'),
        ('skipped', 'Skipped'),
    ], string='Outcome', required=True, index=True)
    order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', ondelete='set null')
    order_state = fields.Selection(
        related='order_id.state', string='Order Status', readonly=True)
    note = fields.Char(string='Note')
    company_id = fields.Many2one(
        related='recurring_id.company_id', store=True, string='Company')

    _occurrence_uniq = models.Constraint(
        'unique(recurring_id, occurrence_date)',
        "An occurrence date can only be handled once per recurring rental.",
    )
