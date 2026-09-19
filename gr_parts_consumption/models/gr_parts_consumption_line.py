# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrPartsConsumptionLine(models.Model):
    _name = 'gr.parts.consumption.line'
    _description = 'Generator Maintenance Parts Consumption'
    _order = 'job_id, id'

    job_id = fields.Many2one(
        'gr.maintenance.job', string='Maintenance Job', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='job_id.company_id', store=True, string='Company')
    asset_id = fields.Many2one(
        related='job_id.asset_id', store=True, string='Asset')
    product_id = fields.Many2one(
        'product.product', string='Part', required=True,
        domain="[('is_storable', '=', True)]")
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit', related='product_id.uom_id', readonly=True)
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, string='Currency')

    unit_cost = fields.Monetary(
        string='Unit Cost', currency_field='currency_id', readonly=True,
        help="Snapshot of the part's cost (last purchase price) at the moment "
             "of consumption; does not change if the product cost later changes.")
    subtotal_cost = fields.Monetary(
        string='Subtotal', currency_field='currency_id',
        compute='_compute_subtotal', store=True)

    move_id = fields.Many2one(
        'stock.move', string='Stock Move', readonly=True, copy=False,
        help="The outgoing stock move that decremented inventory for this part.")
    picking_id = fields.Many2one(
        'stock.picking', string='Stock Picking', readonly=True, copy=False,
        help="The internal stock transfer that issued the part to maintenance.")
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse',
        compute='_compute_locations', store=True, readonly=False)
    source_location_id = fields.Many2one(
        'stock.location', string='Source Location',
        compute='_compute_locations', store=True, readonly=False)
    dest_location_id = fields.Many2one(
        'stock.location', string='Maintenance Consumption Location',
        compute='_compute_locations', store=True, readonly=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('consumed', 'Consumed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False)

    @api.depends('quantity', 'unit_cost')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal_cost = (line.quantity or 0.0) * (line.unit_cost or 0.0)

    @api.depends('company_id')
    def _compute_locations(self):
        for line in self:
            if not line.company_id:
                line.warehouse_id = False
                line.source_location_id = False
                line.dest_location_id = False
                continue
            if not line.warehouse_id:
                line.warehouse_id = line._default_warehouse()
            if line.warehouse_id and not line.source_location_id:
                line.source_location_id = line.warehouse_id.lot_stock_id
            if not line.dest_location_id:
                line.dest_location_id = line._default_dest_location()

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            # show the current cost as a preview (final snapshot taken on consume)
            self.unit_cost = self.product_id.standard_price

    # ------------------------------------------------------------------
    def _source_location(self):
        """Warehouse stock location for this company."""
        self.ensure_one()
        if self.source_location_id:
            return self.source_location_id
        warehouse = self.warehouse_id or self._default_warehouse()
        if not warehouse:
            raise UserError(_(
                "No warehouse configured for company %s.") % self.company_id.name)
        return warehouse.lot_stock_id

    def _dest_location(self):
        """Company production location (parts are consumed/used up)."""
        self.ensure_one()
        if self.dest_location_id:
            return self.dest_location_id
        return self._default_dest_location()

    def _default_warehouse(self):
        self.ensure_one()
        return self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1)

    def _default_dest_location(self):
        self.ensure_one()
        prod_loc = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            '|', ('company_id', '=', self.company_id.id),
            ('company_id', '=', False),
        ], limit=1)
        if not prod_loc:
            # fall back to inventory loss / scrap
            prod_loc = self.env['stock.location'].search([
                ('scrap_location', '=', True)], limit=1)
        if not prod_loc:
            raise UserError(_("No production/scrap location available."))
        return prod_loc

    def _available_qty(self, location):
        self.ensure_one()
        return self.env['stock.quant']._get_available_quantity(
            self.product_id, location)

    def _prepare_issue_picking_vals(self, src, dest):
        self.ensure_one()
        picking_type = (self.warehouse_id or self._default_warehouse()).int_type_id
        return {
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'origin': self.job_id.name,
            'company_id': self.company_id.id,
        }

    # ------------------------------------------------------------------
    def action_consume(self):
        """Create and complete an outgoing stock move, snapshot the cost."""
        for line in self:
            if line.state != 'draft':
                raise UserError(_("Only draft lines can be consumed."))
            if line.quantity <= 0:
                raise UserError(_("Quantity must be positive."))
            src = line._source_location()
            dest = line._dest_location()
            available_qty = line._available_qty(src)
            if line.quantity > available_qty:
                raise UserError(_(
                    "Cannot issue %(qty)s %(uom)s of %(part)s. Available "
                    "quantity in %(location)s is %(available)s %(uom)s.",
                    qty=line.quantity,
                    available=available_qty,
                    uom=line.product_uom_id.display_name or '',
                    part=line.product_id.display_name,
                    location=src.display_name))
            picking = self.env['stock.picking'].create(
                line._prepare_issue_picking_vals(src, dest))
            move = self.env['stock.move'].create({
                # Odoo 19 dropped stock.move.name; the writable move description
                # is description_picking (stored via description_picking_manual).
                'description_picking': _("Parts: %s") % (line.job_id.name or ''),
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'picking_id': picking.id,
                'company_id': line.company_id.id,
            })
            move._action_confirm()
            move._action_assign()
            # set the done quantity then validate
            move.quantity = line.quantity
            move.picked = True
            move._action_done()
            # Set all line fields in a SINGLE write so dependent stored computes
            # (subtotal_cost -> job.total_parts_cost) recompute once, against the
            # final 'consumed' state. Setting unit_cost before state separately
            # would trigger an intermediate recompute while state is still
            # 'draft', storing total_parts_cost = 0 and leaving a stale value.
            line.write({
                'unit_cost': line.product_id.standard_price,
                'move_id': move.id,
                'picking_id': picking.id,
                'warehouse_id': line.warehouse_id.id,
                'source_location_id': src.id,
                'dest_location_id': dest.id,
                'state': 'consumed',
            })
        return True

    def action_cancel(self):
        for line in self:
            if line.state == 'consumed':
                raise UserError(_(
                    "Consumed parts cannot be cancelled here; reverse the stock "
                    "move in Inventory if a correction is needed."))
            line.state = 'cancelled'
        return True
