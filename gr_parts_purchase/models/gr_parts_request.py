# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrMaintenanceJobRequests(models.Model):
    _inherit = 'gr.maintenance.job'

    parts_request_ids = fields.One2many(
        'gr.parts.request', 'job_id', string='Parts Requests')
    parts_request_count = fields.Integer(
        string='Requests', compute='_compute_parts_request_count')

    def _compute_parts_request_count(self):
        Req = self.env['gr.parts.request']
        for job in self:
            job.parts_request_count = Req.search_count([('job_id', '=', job.id)])

    def action_complete(self):
        for job in self:
            open_requests = job.parts_request_ids.filtered(
                lambda req: req.state != 'cancelled')
            blocking_requests = open_requests.filtered(
                lambda req: (
                    req.qty_remaining_to_issue > 0
                    or req.qty_outstanding > 0
                ))
            if blocking_requests:
                raise UserError(_(
                    "Cannot complete maintenance job %(job)s while spare-parts "
                    "requests still have unissued or uninstalled quantities: "
                    "%(requests)s",
                    job=job.display_name,
                    requests=', '.join(blocking_requests.mapped('name'))))
        return super().action_complete()


class GrPartsRequest(models.Model):
    """A request for a part FOR A SPECIFIC generator, raised against a
    maintenance job. Generates a purchase order that is born linked to the unit,
    and later reconciles ordered-for-unit against installed-on-unit."""
    _name = 'gr.parts.request'
    _description = 'Generator Parts Request (for a specific unit)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Request Reference', required=True, copy=False, tracking=True,
        default=lambda self: _('New'))
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    job_id = fields.Many2one(
        'gr.maintenance.job', string='Maintenance Job', required=True,
        index=True, tracking=True, ondelete='cascade',
        help="The job that needs the part. Carries the equipment / Asset No.")
    asset_id = fields.Many2one(
        'gr.generator.asset', string='Equipment (Asset No)',
        related='job_id.asset_id', store=True, readonly=True,
        help="The specific generator this part is ordered for.")
    product_id = fields.Many2one(
        'product.product', string='Part', required=True,
        domain="[('purchase_ok', '=', True)]")
    quantity = fields.Float(
        string='Required Quantity', default=1.0, required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit', related='product_id.uom_id', readonly=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True,
        default=lambda self: self._default_warehouse(),
        domain="[('company_id', '=', company_id)]")
    source_location_id = fields.Many2one(
        'stock.location', string='Source Location',
        related='warehouse_id.lot_stock_id', store=True, readonly=True)

    purpose = fields.Selection([
        ('change_oil', 'Change Oil Service'),
        ('repair', 'Repair'),
        ('replacement', 'Replacement'),
    ], string='Purpose', default='repair', required=True,
        help="Matches the Warehouse Issuance 'purpose of parts releasing'.")

    vendor_id = fields.Many2one(
        'res.partner', string='Preferred Vendor',
        help="Vendor to raise the purchase order against.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('purchased', 'Purchased'),
        ('received', 'Received'),
        ('installed', 'Installed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    purchase_order_id = fields.Many2one(
        'purchase.order', string='Purchase Order', readonly=True, copy=False)
    purchase_line_id = fields.Many2one(
        'purchase.order.line', string='PO Line', readonly=True, copy=False)
    purchase_qty_ordered = fields.Float(
        string='Purchased Quantity', compute='_compute_purchase_quantities')
    purchase_qty_received = fields.Float(
        string='Received Quantity', compute='_compute_purchase_quantities')

    # Reconciliation: ordered-for-unit vs installed-on-unit.
    consumption_line_ids = fields.One2many(
        'gr.parts.consumption.line', 'request_id', string='Installed As')
    stock_move_id = fields.Many2one(
        'stock.move', string='Stock Move', compute='_compute_stock_links')
    stock_picking_id = fields.Many2one(
        'stock.picking', string='Stock Picking', compute='_compute_stock_links')
    available_qty = fields.Float(
        string='Available Quantity', compute='_compute_stock_quantities')
    qty_issued = fields.Float(
        string='Issued Quantity', compute='_compute_reconcile', store=True)
    qty_installed = fields.Float(
        string='Installed Quantity', default=0.0, tracking=True)
    qty_remaining_to_issue = fields.Float(
        string='Remaining Quantity', compute='_compute_reconcile', store=True)
    qty_shortage_to_buy = fields.Float(
        string='Shortage to Buy', compute='_compute_shortage_to_buy')
    qty_outstanding = fields.Float(
        string='Uninstalled Quantity', compute='_compute_reconcile', store=True,
        help="Required for this unit but not yet installed on it. A positive "
             "value that lingers is the parts-leakage early warning.")
    reconciled = fields.Boolean(
        string='Reconciled', compute='_compute_reconcile', store=True,
        help="True when everything ordered for this unit has been installed on "
             "it (no leakage).")

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        "The parts-request reference must be unique per company.",
    )

    @api.depends('consumption_line_ids.state', 'consumption_line_ids.quantity',
                 'quantity', 'qty_installed')
    def _compute_reconcile(self):
        for req in self:
            consumed = req.consumption_line_ids.filtered(
                lambda l: l.state == 'consumed')
            issued = sum(consumed.mapped('quantity'))
            installed = min(req.qty_installed or 0.0, issued)
            req.qty_issued = issued
            req.qty_remaining_to_issue = max(0.0, (req.quantity or 0.0) - issued)
            req.qty_outstanding = max(0.0, (req.quantity or 0.0) - installed)
            req.reconciled = bool(req.quantity and installed >= req.quantity)

    @api.depends('product_id', 'source_location_id')
    def _compute_stock_quantities(self):
        Quant = self.env['stock.quant']
        for req in self:
            if not req.product_id or not req.source_location_id:
                req.available_qty = 0.0
                continue
            req.available_qty = Quant._get_available_quantity(
                req.product_id, req.source_location_id)

    @api.depends('consumption_line_ids.move_id',
                 'consumption_line_ids.picking_id')
    def _compute_stock_links(self):
        for req in self:
            lines = req.consumption_line_ids.filtered(lambda line: line.move_id)
            req.stock_move_id = lines[:1].move_id
            req.stock_picking_id = lines[:1].picking_id

    @api.depends('purchase_line_id.product_qty', 'purchase_line_id.qty_received')
    def _compute_purchase_quantities(self):
        for req in self:
            req.purchase_qty_ordered = (
                req.purchase_line_id.product_qty if req.purchase_line_id else 0.0)
            req.purchase_qty_received = (
                req.purchase_line_id.qty_received if req.purchase_line_id else 0.0)

    @api.depends('quantity', 'qty_issued', 'available_qty',
                 'purchase_line_id.product_qty',
                 'purchase_order_id.state')
    def _compute_shortage_to_buy(self):
        for req in self:
            req.qty_shortage_to_buy = max(
                0.0,
                (req.quantity or 0.0)
                - (req.qty_issued or 0.0)
                - (req.available_qty or 0.0)
                - req._open_purchase_qty())

    @api.model
    def _default_warehouse(self):
        return self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id)], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gr.parts.request') or _('New')
            if not vals.get('warehouse_id'):
                company = self.env['res.company'].browse(
                    vals.get('company_id')) if vals.get('company_id') else self.env.company
                warehouse = self.env['stock.warehouse'].search([
                    ('company_id', '=', company.id)], limit=1)
                vals['warehouse_id'] = warehouse.id
        return super().create(vals_list)

    # ------------------------------------------------------------------
    def _open_purchase_qty(self):
        self.ensure_one()
        if not self.purchase_line_id or self.purchase_order_id.state == 'cancel':
            return 0.0
        return self.purchase_line_id.product_qty or 0.0

    def _ensure_positive_quantity(self):
        for req in self:
            if req.quantity <= 0:
                raise UserError(_("Required quantity must be positive."))

    def action_issue_available(self):
        """Issue only the stock that is physically available for this request."""
        Line = self.env['gr.parts.consumption.line']
        for req in self:
            if req.state in ('installed', 'cancelled'):
                raise UserError(_(
                    "Cannot issue parts for request %s in its current state.")
                    % req.name)
            req._ensure_positive_quantity()
            req.invalidate_recordset([
                'available_qty', 'qty_issued', 'qty_remaining_to_issue',
                'qty_shortage_to_buy'])
            qty_to_issue = min(req.qty_remaining_to_issue, req.available_qty)
            if qty_to_issue <= 0:
                raise UserError(_(
                    "No available quantity to issue for request %s.") % req.name)
            line = Line.create({
                'request_id': req.id,
                'job_id': req.job_id.id,
                'product_id': req.product_id.id,
                'quantity': qty_to_issue,
                'warehouse_id': req.warehouse_id.id,
                'source_location_id': req.source_location_id.id,
            })
            line.action_consume()
            req.invalidate_recordset([
                'qty_issued', 'qty_remaining_to_issue', 'qty_shortage_to_buy',
                'available_qty'])
            if req.state == 'draft':
                req.state = 'issued'
            req.message_post(
                body=_(
                    "Issued %(qty)s %(uom)s of %(part)s from %(location)s.",
                    qty=qty_to_issue,
                    uom=req.product_uom_id.display_name or '',
                    part=req.product_id.display_name,
                    location=req.source_location_id.display_name),
                subtype_xmlid='mail.mt_note')
        return True

    def action_generate_po(self):
        """Create a purchase order for the shortage only."""
        for req in self:
            cancelled_po = (
                req.purchase_order_id and req.purchase_order_id.state == 'cancel')
            req._ensure_positive_quantity()
            if (req.purchase_line_id
                    and req.purchase_order_id.state != 'cancel'):
                raise UserError(_(
                    "A purchase order already covers the current shortage for "
                    "request %s.") % req.name)
            if req.state not in ('draft', 'issued') and not cancelled_po:
                raise UserError(_("Only open requests can be purchased."))
            if not req.vendor_id:
                raise UserError(_(
                    "Set a preferred vendor before generating the purchase "
                    "order for request %s.") % req.name)
            qty_to_buy = req.qty_shortage_to_buy
            if qty_to_buy <= 0:
                raise UserError(_(
                    "There is no shortage to purchase for request %s.") % req.name)
            po = self.env['purchase.order'].create({
                'partner_id': req.vendor_id.id,
                'company_id': req.company_id.id,
                'origin': req.name,
            })
            po_line = self.env['purchase.order.line'].create({
                'order_id': po.id,
                'product_id': req.product_id.id,
                'product_qty': qty_to_buy,
                'product_uom_id': req.product_uom_id.id,
                'name': _("%(part)s for %(asset)s (req %(req)s)",
                          part=req.product_id.display_name,
                          asset=req.asset_id.display_name or '',
                          req=req.name),
            })
            req.write({
                'purchase_order_id': po.id,
                'purchase_line_id': po_line.id,
                'state': 'purchased',
            })
            req.message_post(
                body=_(
                    "Purchase order %(po)s generated for shortage quantity "
                    "%(qty)s %(uom)s for %(asset)s.",
                    po=po.name,
                    qty=qty_to_buy,
                    uom=req.product_uom_id.display_name or '',
                    asset=req.asset_id.display_name or ''),
                subtype_xmlid='mail.mt_note')
        return self.action_view_po()

    def action_view_po(self):
        self.ensure_one()
        if not self.purchase_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Order'),
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
        }

    def action_mark_received(self):
        for req in self:
            if req.state != 'purchased':
                raise UserError(_("Only purchased requests can be received."))
            req.invalidate_recordset([
                'purchase_qty_received', 'purchase_qty_ordered',
                'available_qty'])
            if req.purchase_qty_received <= 0:
                raise UserError(_(
                    "Receive the purchase order for request %s before marking "
                    "it received.") % req.name)
            req.state = 'received'
        return True

    def action_register_installation(self):
        for req in self:
            if req.state == 'cancelled':
                raise UserError(_("Cancelled requests cannot be installed."))
            if req.qty_issued <= req.qty_installed:
                raise UserError(_(
                    "There is no issued quantity waiting for installation on "
                    "request %s.") % req.name)
            req.qty_installed = req.qty_issued
            if req.qty_installed >= req.quantity:
                req.state = 'installed'
            req.message_post(
                body=_(
                    "Installed %(qty)s %(uom)s of %(part)s on %(asset)s.",
                    qty=req.qty_installed,
                    uom=req.product_uom_id.display_name or '',
                    part=req.product_id.display_name,
                    asset=req.asset_id.display_name or ''),
                subtype_xmlid='mail.mt_note')
        return True

    def action_cancel(self):
        for req in self:
            if req.state == 'installed':
                raise UserError(_(
                    "Cannot cancel request %s: parts already installed.")
                    % req.name)
            req.state = 'cancelled'
        return True

    def _check_installed(self):
        """Kept for compatibility; installation is now registered explicitly."""
        for req in self:
            if req.reconciled and req.state in ('received', 'purchased', 'issued'):
                req.state = 'installed'
