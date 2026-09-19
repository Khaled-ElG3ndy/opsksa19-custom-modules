# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# The audited, server-side-only pass key defined by the dispatch hard-stop module.
# Imported (not re-declared) so the two modules can never drift apart.
from odoo.addons.strx_cabin_dispatch_control.models.stock_move_line import BYPASS_KEY


class StrxCabinSubstitution(models.Model):
    """Controlled specification-change request — the ONLY sanctioned route past the
    dispatch hard-stop.

    Same spec / different serial  -> free reallocation, logged, no approval.
    Different spec (e.g. 5×3→5×5)  -> submitted → approved/rejected. On approval the
    allocation is re-pointed to the proposed serial and the reserved delivery is
    updated under the BYPASS_KEY context, so the approved unit — and only it — passes.
    """
    _name = 'strx.cabin.substitution'
    _description = 'Cabin Substitution Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       index=True, default=lambda self: _('New'))

    allocation_id = fields.Many2one(
        'strx.cabin.allocation', string='Allocation', required=True, ondelete='cascade',
        index=True, tracking=True)
    order_id = fields.Many2one('sale.order', related='allocation_id.order_id',
                               store=True, readonly=True)
    order_line_id = fields.Many2one('sale.order.line',
                                    related='allocation_id.order_line_id',
                                    store=True, readonly=True)
    partner_id = fields.Many2one('res.partner', related='allocation_id.partner_id',
                                 store=True, readonly=True)

    # --- Original (snapshot from the allocation at creation) ---
    original_product_id = fields.Many2one('product.product', string='Original Spec',
                                          readonly=True)
    original_lot_id = fields.Many2one('stock.lot', string='Original Serial',
                                      domain="[('id', 'in', allocation_lot_ids)]")
    allocation_lot_ids = fields.Many2many(
        'stock.lot', related='allocation_id.lot_ids', readonly=True)

    # --- Proposed ---
    proposed_product_id = fields.Many2one(
        'product.product', string='Proposed Spec', tracking=True,
        domain="[('strx_is_cabin', '=', True)]")
    proposed_lot_id = fields.Many2one(
        'stock.lot', string='Proposed Serial', tracking=True,
        domain="['&', '&', ('product_id', '=', proposed_product_id),"
               " ('strx_hidden_from_selection', '=', False),"
               " ('strx_selectable', '=', True)]")

    is_spec_change = fields.Boolean(string='Specification Change',
                                    compute='_compute_is_spec_change', store=True)
    no_approval_required = fields.Boolean(compute='_compute_is_spec_change', store=True)

    # --- Impact / justification (requirement #3) ---
    reason = fields.Text(string='Reason', tracking=True)
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id',
                                  readonly=True)
    price_impact = fields.Monetary(
        string='Price Impact', currency_field='currency_id', tracking=True,
        help="Change to what the customer is charged. Zero for a free upgrade.")
    commercial_value = fields.Monetary(
        string='Commercial Value', currency_field='currency_id',
        compute='_compute_commercial_value', store=True, readonly=False, tracking=True,
        help="List value of the specification change. For a FREE upgrade this is what "
             "is being given away — it must be recorded even when the price impact is 0.")
    is_free_upgrade = fields.Boolean(compute='_compute_is_free_upgrade', store=True)
    transport_impact = fields.Selection(
        selection=[('none', 'No change'), ('minor', 'Minor'), ('major', 'Major')],
        string='Transport Impact', default='none', tracking=True)
    transport_note = fields.Char(string='Transport Note')
    site_fit_confirmed = fields.Boolean(string='Site-Fit Confirmed', tracking=True,
                                        help="The proposed unit fits the customer site.")

    # --- Workflow / audit (requirement #3, #5) ---
    state = fields.Selection(
        selection=[('draft', 'Draft'), ('submitted', 'Submitted'),
                   ('approved', 'Approved'), ('rejected', 'Rejected')],
        string='Status', default='draft', required=True, copy=False, tracking=True)
    requester_id = fields.Many2one('res.users', string='Requested By', readonly=True,
                                   default=lambda self: self.env.user)
    request_date = fields.Datetime(string='Requested On', readonly=True,
                                   default=fields.Datetime.now)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    approver_id = fields.Many2one('res.users', string='Decided By', readonly=True,
                                  copy=False)
    decision_date = fields.Datetime(string='Decision On', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False)

    company_id = fields.Many2one('res.company', related='order_id.company_id',
                                 store=True, readonly=True)

    # ------------------------------------------------------------------ compute
    @api.depends('original_product_id', 'proposed_product_id')
    def _compute_is_spec_change(self):
        for sub in self:
            change = bool(sub.proposed_product_id) \
                and sub.proposed_product_id != sub.original_product_id
            sub.is_spec_change = change
            sub.no_approval_required = not change

    @api.depends('original_product_id', 'proposed_product_id')
    def _compute_commercial_value(self):
        for sub in self:
            delta = (sub.proposed_product_id.list_price or 0.0) \
                - (sub.original_product_id.list_price or 0.0)
            # Default suggestion: the upgrade value (never negative). Editable.
            sub.commercial_value = max(delta, 0.0)

    @api.depends('is_spec_change', 'original_product_id', 'proposed_product_id',
                 'price_impact')
    def _compute_is_free_upgrade(self):
        # A free upgrade = the proposed unit is intrinsically more valuable than the
        # original, given at no (or negative) extra charge. Deliberately independent of
        # commercial_value, so the "record the value" guard can actually fire.
        for sub in self:
            is_upgrade = sub.is_spec_change and (
                (sub.proposed_product_id.list_price or 0.0)
                > (sub.original_product_id.list_price or 0.0))
            sub.is_free_upgrade = bool(is_upgrade and sub.price_impact <= 0)

    # ----------------------------------------------------------------- onchange
    @api.onchange('allocation_id')
    def _onchange_allocation_id(self):
        if self.allocation_id:
            self.original_product_id = self.allocation_id.product_id
            self.original_lot_id = (
                self.allocation_id.lot_ids
                if len(self.allocation_id.lot_ids) == 1 else False)
            if not self.proposed_product_id:
                self.proposed_product_id = self.allocation_id.product_id

    @api.onchange('proposed_product_id')
    def _onchange_proposed_product_id(self):
        if self.proposed_lot_id and self.proposed_lot_id.product_id != self.proposed_product_id:
            self.proposed_lot_id = False

    # ------------------------------------------------------------------- create
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'strx.cabin.substitution') or _('New')
            alloc = self.env['strx.cabin.allocation'].browse(vals.get('allocation_id'))
            if alloc:
                vals.setdefault('original_product_id', alloc.product_id.id)
                if len(alloc.lot_ids) == 1:
                    vals.setdefault('original_lot_id', alloc.lot_ids.id)
                vals.setdefault('proposed_product_id',
                                vals.get('proposed_product_id') or alloc.product_id.id)
        return super().create(vals_list)

    # -------------------------------------------------------------- validation
    def _check_ready_to_decide(self):
        self.ensure_one()
        if not self.original_lot_id:
            raise UserError(_("Select the original serial to replace."))
        if self.original_lot_id not in self.allocation_id.lot_ids:
            raise UserError(_(
                "The original serial is no longer part of this allocation. Refresh "
                "the request and select one of its current serials."))
        if not self.proposed_lot_id:
            raise UserError(_("Select the proposed serial before proceeding."))
        if self.proposed_lot_id.product_id != self.proposed_product_id:
            raise ValidationError(_("The proposed serial does not match the proposed "
                                    "specification."))
        if self.proposed_lot_id in (
                self.allocation_id.lot_ids - self.original_lot_id):
            raise UserError(_(
                "The proposed serial is already selected on this allocation. Choose "
                "a different available serial."))
        if self.proposed_lot_id not in self.allocation_id.lot_ids \
                and not self.proposed_lot_id.strx_selectable:
            raise UserError(_(
                "Proposed serial %(serial)s is %(state)s and cannot be selected.",
                serial=self.proposed_lot_id.name,
                state=self.proposed_lot_id.strx_state_label
                    or self.proposed_lot_id.strx_readiness_state))
        if self.is_spec_change:
            if len(self.allocation_id.lot_ids) > 1:
                raise UserError(_(
                    "A specification change for a multi-serial allocation must replace "
                    "the complete ordered group. Change the sale-line specification "
                    "before dispatch, or create a separate approved commercial order."))
            if not self.reason:
                raise UserError(_("A specification change requires a reason."))
            if not self.site_fit_confirmed:
                raise UserError(_("Confirm the proposed unit fits the site before "
                                  "submitting a specification change."))
            # Requirement #4: zero-charge must never mean zero-record.
            if self.is_free_upgrade and self.commercial_value <= 0:
                raise UserError(_("This is a free upgrade — record its commercial value "
                                  "so management can see what is being given away."))

    def _only_approvers(self):
        if not (self.env.user.has_group('sales_team.group_sale_manager')
                or self.env.user.has_group('stock.group_stock_manager')):
            raise UserError(_("Only a Commercial Manager may approve or reject a "
                              "specification substitution."))

    # ---------------------------------------------------------------- workflow
    def action_submit(self):
        for sub in self:
            sub._check_ready_to_decide()
            if sub.no_approval_required:
                # Same spec, different serial: free reallocation, logged, no approval.
                sub._strx_apply()
                sub.write({'state': 'approved', 'approver_id': sub.requester_id.id,
                           'decision_date': fields.Datetime.now()})
                sub.message_post(body=_(
                    "Same-specification reallocation applied — no approval required."))
            else:
                sub.write({'state': 'submitted',
                           'submitted_date': fields.Datetime.now()})

    def action_approve(self):
        for sub in self:
            sub._only_approvers()
            if sub.state != 'submitted':
                raise UserError(_("Only a submitted request can be approved."))
            sub._strx_apply()
            sub.write({'state': 'approved', 'approver_id': self.env.user.id,
                       'decision_date': fields.Datetime.now()})
            sub.message_post(body=_(
                "Substitution approved: %(orig)s → %(new)s (commercial value %(val)s).",
                orig=sub.original_lot_id.name or sub.original_product_id.display_name,
                new=sub.proposed_lot_id.name,
                val=sub.commercial_value))

    def action_reject(self):
        for sub in self:
            sub._only_approvers()
            if sub.state != 'submitted':
                raise UserError(_("Only a submitted request can be rejected."))
            if not sub.rejection_reason:
                raise UserError(_("Give a rejection reason."))
            sub.write({'state': 'rejected', 'approver_id': self.env.user.id,
                       'decision_date': fields.Datetime.now()})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    # ============================================================ APPLY (BYPASS)
    def _strx_apply(self):
        """Install the approved substitution.

        1. Re-point the allocation to the proposed product + serial (requirement #5).
        2. Release the old serial, commit the new one (readiness).
        3. Re-point the reserved delivery to the new serial — the ONE place the dispatch
           hard-stop is deliberately passed, via the server-side BYPASS_KEY context.
        """
        self.ensure_one()
        alloc = self.allocation_id
        old_lot = self.original_lot_id
        new_lot = self.proposed_lot_id

        # 1. Allocation becomes the record of the NEW approved spec/serial.
        #    (Not hard-stop-guarded, so no bypass needed here.)
        new_lots = (alloc.lot_ids - old_lot) | new_lot
        alloc.write({
            'product_id': self.proposed_product_id.id,
            'lot_ids': [(6, 0, new_lots.ids)],
        })

        # 2. Readiness: free the old unit, commit the new one.
        if old_lot and old_lot != new_lot and old_lot.strx_readiness_state == 'allocated':
            old_lot._strx_set_readiness(
                'available', reason=_("Freed by substitution %(ref)s", ref=self.name))
        if new_lot.strx_readiness_state != 'allocated':
            new_lot._strx_set_readiness(
                'allocated', reason=_("Committed by substitution %(ref)s", ref=self.name))

        # 3. Re-point the live delivery under the UNFORGEABLE server-side pass.
        self._strx_repoint_delivery()

    def _strx_repoint_delivery(self):
        """Update the still-open outgoing delivery so the proposed serial is staged.

        Runs under .sudo() (superuser mode) + the BYPASS_KEY context. The hard-stop
        honours the bypass ONLY under su, so this pass is reproducible only from here,
        never from a user RPC. All records created/reserved inherit this env.
        """
        self.ensure_one()
        moves = self.order_line_id.move_ids.filtered(
            lambda m: m.picking_id.picking_type_id.code == 'outgoing'
            and m.state not in ('done', 'cancel'))
        picking = moves.picking_id[:1]
        if not picking:
            return  # nothing staged yet; allocation update alone authorises the new unit

        # sudo() => env.su is True (unforgeable); the context key alone is not enough.
        picking = picking.sudo().with_context(**{BYPASS_KEY: True})
        Move = self.env['stock.move'].sudo().with_context(**{BYPASS_KEY: True})
        MoveLine = self.env['stock.move.line'].sudo().with_context(**{BYPASS_KEY: True})

        picking.do_unreserve()

        if self.proposed_product_id != self.original_product_id:
            # Different spec: retire the old-product moves and add one for the new spec.
            old_moves = picking.move_ids.filtered(
                lambda m: m.product_id == self.original_product_id)
            old_moves._action_cancel()
            new_move = Move.create({
                # Odoo 19 dropped stock.move.name; the picking description is
                # derived from the product instead.
                'product_id': self.proposed_product_id.id,
                'product_uom_qty': 1,
                'product_uom': self.proposed_product_id.uom_id.id,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
            new_move._action_confirm()

        picking.action_assign()

        # Pin the exact proposed serial on the relevant move line.
        ml = picking.move_line_ids.filtered(
            lambda l: l.product_id == self.proposed_product_id)[:1]
        if ml:
            ml.write({'lot_id': self.proposed_lot_id.id, 'quantity': 1})
        else:
            move = picking.move_ids.filtered(
                lambda m: m.product_id == self.proposed_product_id
                and m.state not in ('done', 'cancel'))[:1]
            if move:
                MoveLine.create({
                    'move_id': move.id, 'picking_id': picking.id,
                    'product_id': self.proposed_product_id.id,
                    'lot_id': self.proposed_lot_id.id, 'quantity': 1,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
