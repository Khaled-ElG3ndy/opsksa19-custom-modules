# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GrSubletAgreement(models.Model):
    """The rent-in side of a sublet: ABSAL rents a unit IN from a vendor for a
    period, then rents it OUT to customers (one or more rental orders on the same
    physical unit). Owns the born-linked rent-in PO; computes margin against the
    unit's invoiced rental revenue; flags vendor-payable exposure."""
    _name = 'gr.sublet.agreement'
    _description = 'Sublet Rental Agreement (rent-in)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    _FORBIDDEN_RENT_IN_ACCOUNT_TYPES = ('asset_fixed', 'expense_depreciation')

    name = fields.Char(
        string='Agreement Ref', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)

    asset_id = fields.Many2one(
        'gr.generator.asset', string='Equipment (Asset No)', required=True,
        index=True, tracking=True,
        domain="[('owner_type', '=', 'rented_in')]",
        help="The rented-in unit. Must be equipment flagged Third-Party.")
    serial_number = fields.Char(
        related='asset_id.serial_number', store=True, readonly=True)
    supplier_equipment_ref = fields.Char(
        string='Supplier Equipment Reference',
        related='asset_id.supplier_equipment_ref', readonly=False,
        help="The supplier's own reference for the unit (e.g. ABC-GEN-55). "
             "Stored on the equipment record; editable here for convenience.")
    vendor_id = fields.Many2one(
        'res.partner', string='Supplier (rented from)', required=True, tracking=True,
        help="The third party ABSAL rents the unit from and pays.")

    date_start = fields.Date(string='Supplier Rental Start', required=True,
                             default=fields.Date.context_today, tracking=True,
                             index=True)
    date_end = fields.Date(string='Supplier Rental End (due back)', tracking=True,
                           index=True,
                           help="When ABSAL must return the unit to the supplier. "
                                "Customer rentals of this unit may not run past "
                                "this date.")
    note = fields.Text(
        string='Notes',
        help="Free-text notes about the supplier rental: conditions, "
             "accessories included, delivery arrangements.")

    # rent-in cost side
    rent_in_product_id = fields.Many2one(
        'product.product', string='Rent-in Service',
        domain="[('purchase_ok', '=', True), ('type', '=', 'service')]",
        help="The service/product line used on the rent-in PO (e.g. a monthly "
             "generator rental service).")
    rent_in_expense_account_id = fields.Many2one(
        'account.account', string='Rent-in Expense Account',
        compute='_compute_rent_in_expense_account',
        help="The operating expense account expected on vendor bills for this "
             "rent-in service. Fixed-asset and depreciation accounts are "
             "blocked for third-party rentals.")
    rent_in_amount = fields.Monetary(
        string='Rent-in Amount', currency_field='currency_id', tracking=True,
        help="Agreed cost ABSAL pays the vendor for the rent-in period.")
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    purchase_order_id = fields.Many2one(
        'purchase.order', string='Rent-in PO', readonly=True, copy=False)
    purchase_line_id = fields.Many2one(
        'purchase.order.line', string='Rent-in PO Line', readonly=True, copy=False)
    po_state = fields.Selection(
        related='purchase_order_id.state', string='PO Status', readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('committed', 'Committed'),    # PO raised - ABSAL is on the hook
        ('returned', 'Returned'),      # unit given back to vendor
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    # rent-out side (the customer rentals for this same physical unit)
    rental_order_ids = fields.One2many(
        'gr.rental.order', 'sublet_agreement_id', string='Rent-out Orders')
    rental_order_count = fields.Integer(
        string='Rent-out Order Count', compute='_compute_rentout')
    direct_cost_ids = fields.One2many(
        'gr.sublet.direct.cost', 'agreement_id', string='Direct Costs')

    # margin
    revenue_out = fields.Monetary(
        string='Revenue Out', currency_field='currency_id',
        compute='_compute_margin',
        help="Invoiced rental revenue from the customer rentals of this unit "
             "linked to this agreement.")
    cost_in = fields.Monetary(
        string='Cost In', currency_field='currency_id',
        compute='_compute_margin',
        help="What ABSAL pays the vendor (the rent-in amount).")
    extra_direct_cost = fields.Monetary(
        string='Extra Direct Cost', currency_field='currency_id',
        compute='_compute_margin',
        help="Additional operation costs recorded on this sublet, such as "
             "maintenance, repairs, parts, or vendor-bill expenses.")
    total_cost = fields.Monetary(
        string='Total Cost', currency_field='currency_id',
        compute='_compute_margin',
        help="Vendor rent-in cost plus extra direct costs.")
    margin = fields.Monetary(
        string='Sublet Margin', currency_field='currency_id',
        compute='_compute_margin')
    margin_pct = fields.Float(
        string='Margin %', compute='_compute_margin')

    # vendor-payable exposure
    exposure_flagged = fields.Boolean(
        string='Vendor Exposure', compute='_compute_exposure', store=True,
        help="True when ABSAL's rent-in obligation is still live (committed) "
             "while either the rent-in period has ended (unit overdue back to "
             "vendor) or a customer rental of the unit is still out. A risk "
             "surface for finance.")
    exposure_reason = fields.Char(
        string='Exposure Reason', compute='_compute_exposure', store=True)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The agreement reference must be unique per company.",
    )

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS gr_sublet_agreement_availability_idx
                ON gr_sublet_agreement
             (company_id, state, asset_id, date_start, date_end)
        """)

    # ------------------------------------------------------------------
    def _compute_rentout(self):
        for ag in self:
            ag.rental_order_count = len(ag.rental_order_ids)

    @api.depends('rent_in_amount', 'rental_order_ids', 'rental_order_ids.name',
                 'direct_cost_ids.amount', 'state')
    def _compute_margin(self):
        Move = self.env['account.move']
        for ag in self:
            cost = ag.rent_in_amount or 0.0
            extra_cost = sum(ag.direct_cost_ids.mapped('amount'))
            # revenue-out: posted customer invoices originating from this unit's
            # rent-out orders. If not posted yet, use generated draft customer
            # billing so the margin appears as soon as the billing run creates it.
            revenue = 0.0
            origins = ag.rental_order_ids.mapped('name')
            if origins:
                invoices = Move.search([
                    ('move_type', '=', 'out_invoice'),
                    ('invoice_origin', 'in', origins),
                    ('state', '!=', 'cancel'),
                ])
                posted = invoices.filtered(lambda move: move.state == 'posted')
                revenue = sum((posted or invoices).mapped('amount_untaxed'))
            ag.revenue_out = revenue
            ag.cost_in = cost
            ag.extra_direct_cost = extra_cost
            ag.total_cost = cost + extra_cost
            ag.margin = revenue - ag.total_cost
            ag.margin_pct = (ag.margin / revenue * 100.0) if revenue else 0.0

    @api.depends('rent_in_product_id', 'company_id')
    def _compute_rent_in_expense_account(self):
        for ag in self:
            ag.rent_in_expense_account_id = ag._rent_in_expense_account()

    def _rent_in_expense_account(self):
        self.ensure_one()
        if not self.rent_in_product_id:
            return self.env['account.account']
        product = self.rent_in_product_id.with_company(self.company_id)
        if hasattr(product, '_get_product_accounts'):
            return product._get_product_accounts().get('expense')
        expense_account = (
            product.property_account_expense_id
            or product.categ_id.property_account_expense_categ_id
        )
        if expense_account:
            return expense_account
        if 'expense_account_id' in self.company_id._fields:
            return self.company_id.expense_account_id
        return self.env['account.account']

    @api.depends('state', 'date_end', 'rental_order_ids.state',
                 'purchase_order_id.state')
    def _compute_exposure(self):
        today = fields.Date.context_today(self)
        active_out = ('dispatched', 'installed', 'on_rent',
                      'off_hire_requested', 'returned')
        for ag in self:
            flagged = False
            reason = False
            if ag.state == 'committed':
                unit_still_out = any(
                    o.state in active_out for o in ag.rental_order_ids)
                overdue_to_vendor = bool(ag.date_end and ag.date_end < today)
                if overdue_to_vendor and unit_still_out:
                    flagged = True
                    reason = _("Rent-in period ended and unit still out with a customer")
                elif overdue_to_vendor:
                    flagged = True
                    reason = _("Rent-in period ended; unit not yet returned to vendor")
                elif unit_still_out and not ag.date_end:
                    flagged = True
                    reason = _("Unit out with a customer and no rent-in end date set")
            ag.exposure_flagged = flagged
            ag.exposure_reason = reason

    @api.constrains('date_start', 'date_end')
    def _check_supplier_period(self):
        for ag in self:
            if ag.date_start and ag.date_end and ag.date_end < ag.date_start:
                raise ValidationError(_(
                    "The supplier rental of %(ref)s cannot end (%(end)s) before "
                    "it starts (%(start)s).",
                    ref=ag.name, end=ag.date_end, start=ag.date_start))

    @api.constrains('asset_id', 'vendor_id')
    def _check_third_party_asset_and_vendor(self):
        for ag in self:
            asset = ag.asset_id
            if not asset:
                continue
            if asset.owner_type != 'rented_in':
                label = dict(asset._fields['owner_type'].selection).get(
                    asset.owner_type, asset.owner_type)
                raise ValidationError(_(
                    "Supplier rental agreement %(agreement)s can only be "
                    "linked to Third-Party equipment. %(asset)s is %(owner)s.",
                    agreement=ag.display_name,
                    asset=asset.display_name,
                    owner=label))
            if (ag.vendor_id and asset.owner_partner_id
                    and ag.vendor_id != asset.owner_partner_id):
                raise ValidationError(_(
                    "Supplier rental agreement %(agreement)s uses vendor "
                    "%(vendor)s, but equipment %(asset)s is rented from "
                    "%(supplier)s. Use the equipment supplier so the rent-in "
                    "cost stays tied to the correct third party.",
                    agreement=ag.display_name,
                    vendor=ag.vendor_id.display_name,
                    asset=asset.display_name,
                    supplier=asset.owner_partner_id.display_name))

    @api.constrains('rent_in_product_id', 'company_id')
    def _check_rent_in_product_is_operating_expense(self):
        self._validate_rent_in_product_operating_expense()

    def _validate_rent_in_product_operating_expense(self):
        for ag in self:
            product = ag.rent_in_product_id
            if not product:
                continue
            if product.type != 'service':
                raise ValidationError(_(
                    "Rent-in product %(product)s must be a service product so "
                    "the supplier rental is treated as an operating expense.",
                    product=product.display_name))
            template = product.product_tmpl_id.with_company(ag.company_id)
            if ('asset_category_id' in template._fields
                    and template.asset_category_id):
                raise ValidationError(_(
                    "Rent-in product %(product)s has an Asset Category "
                    "(%(category)s). Remove it or use a plain rental expense "
                    "service product; third-party equipment rentals must not "
                    "create fixed assets or depreciation schedules.",
                    product=product.display_name,
                    category=template.asset_category_id.display_name))
            account = ag._rent_in_expense_account()
            if account and account.account_type in \
                    ag._FORBIDDEN_RENT_IN_ACCOUNT_TYPES:
                raise ValidationError(_(
                    "Rent-in product %(product)s uses account %(account)s, "
                    "which is a fixed-asset/depreciation account. Configure "
                    "an operating expense account before using it for "
                    "third-party equipment rentals.",
                    product=product.display_name,
                    account=account.display_name))

    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.sublet.agreement') or _('New')
        return super().create(vals_list)

    @api.onchange('asset_id')
    def _onchange_asset(self):
        # default the vendor from the equipment's owner (M11 rented_in owner)
        if self.asset_id and self.asset_id.owner_partner_id and not self.vendor_id:
            self.vendor_id = self.asset_id.owner_partner_id

    def action_generate_rent_in_po(self):
        """Create the rent-in purchase order, born linked to this agreement and
        unit (mirrors the M12 born-linked PO pattern)."""
        for ag in self:
            if ag.state != 'draft':
                raise UserError(_("Only draft agreements can raise a rent-in PO."))
            if not ag.vendor_id:
                raise UserError(_("Set the vendor before raising the rent-in PO."))
            if not ag.rent_in_product_id:
                raise UserError(_(
                    "Set a rent-in service product before raising the PO for %s.")
                    % ag.name)
            if ag.rent_in_amount <= 0:
                raise UserError(_("Rent-in amount must be positive."))
            ag._validate_rent_in_product_operating_expense()
            po = self.env['purchase.order'].create({
                'partner_id': ag.vendor_id.id,
                'company_id': ag.company_id.id,
                'origin': ag.name,
            })
            po_line = self.env['purchase.order.line'].create({
                'order_id': po.id,
                'product_id': ag.rent_in_product_id.id,
                'product_qty': 1.0,
                'price_unit': ag.rent_in_amount,
                'name': _("Rent-in %(asset)s from %(vendor)s (%(ref)s)",
                          asset=ag.asset_id.display_name,
                          vendor=ag.vendor_id.display_name, ref=ag.name),
            })
            ag.write({
                'purchase_order_id': po.id,
                'purchase_line_id': po_line.id,
                'state': 'committed',
            })
            ag.message_post(
                body=_("Rent-in PO %(po)s raised for %(asset)s; ABSAL is now on "
                       "the hook to the vendor.",
                       po=po.name, asset=ag.asset_id.display_name),
                subtype_xmlid='mail.mt_note')
        return self.action_view_po()

    def action_view_po(self):
        self.ensure_one()
        if not self.purchase_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rent-in PO'),
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
        }

    def action_mark_returned(self):
        for ag in self:
            if ag.state != 'committed':
                raise UserError(_("Only committed agreements can be returned."))
            still_out = any(o.state in (
                'dispatched', 'installed', 'on_rent', 'off_hire_requested',
                'returned') for o in ag.rental_order_ids)
            if still_out:
                raise UserError(_(
                    "Cannot return %s to the vendor: the unit is still out with "
                    "a customer. Close the rent-out order(s) first.") % ag.name)
            ag.state = 'returned'
        return True

    def action_cancel(self):
        for ag in self:
            if ag.state == 'returned':
                raise UserError(_("A returned agreement cannot be cancelled."))
            ag.state = 'cancelled'
        return True

    def action_reset_draft(self):
        for ag in self:
            ag.state = 'draft'
        return True

    def action_view_rentout(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rent-out Orders'),
            'res_model': 'gr.rental.order',
            'domain': [('sublet_agreement_id', '=', self.id)],
            'view_mode': 'list,form',
            'context': {'default_sublet_agreement_id': self.id,
                        'default_asset_id': self.asset_id.id},
        }
