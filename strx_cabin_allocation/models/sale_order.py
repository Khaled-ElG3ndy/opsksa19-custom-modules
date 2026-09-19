# -*- coding: utf-8 -*-
import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    strx_allocation_ids = fields.One2many(
        'strx.cabin.allocation', 'order_line_id', string='Cabin Allocations')
    strx_is_free_additional_service = fields.Boolean(
        string='Additional Product',
        related='product_id.strx_is_free_additional_service', readonly=True,
        store=True,
        help="Tick for add-on products or services requested with a cabin, such as "
             "a bathroom tank, ladder, canopy, AC unit, or water tank. These items "
             "are offered in the Additional Products tab and are not cabin assets.")
    strx_rental_start_date = fields.Date(string='Rental Start')
    strx_rental_days = fields.Integer(string='Rental Days')
    strx_expected_return_date = fields.Date(string='Expected Return')

    def _strx_committed_allocation_lots(self):
        """Return the exact serials that are safe to snapshot on an invoice."""
        self.ensure_one()
        allocations = self.strx_allocation_ids.filtered(
            lambda allocation: allocation.state in (
                'allocated', 'dispatched', 'on_rent',
                'returned', 'available', 'done'))
        return allocations.mapped('lot_ids')

    def _prepare_invoice_line(self, **optional_values):
        values = super()._prepare_invoice_line(**optional_values)
        if self.product_id.strx_is_cabin and not self.display_type \
                and not self.is_downpayment:
            lots = self._strx_committed_allocation_lots()
            if lots:
                ordered_lots = lots.sorted(key=lambda lot: (lot.name or '', lot.id))
                values.update({
                    'strx_allocated_lot_ids': [(6, 0, ordered_lots.ids)],
                    'strx_allocated_serial_numbers': ', '.join(
                        ordered_lots.mapped('name')),
                })
        return values

    @api.depends('product_id', 'state', 'qty_invoiced', 'qty_delivered')
    @api.depends_context('strx_allow_confirmed_cabin_spec_change')
    def _compute_product_updatable(self):
        super()._compute_product_updatable()
        if not self.env.context.get('strx_allow_confirmed_cabin_spec_change'):
            return
        for line in self:
            if line.order_id.state in ('sale', 'done') \
                    and not line.order_id.locked \
                    and line.product_id.strx_is_cabin \
                    and line.qty_invoiced <= 0 \
                    and line.qty_delivered <= 0:
                line.product_updatable = True

    @api.model_create_multi
    def create(self, vals_list):
        self._strx_reject_confirmed_cabin_line_create(vals_list)
        self._strx_prepare_rental_period_vals(vals_list)
        lines = super().create(vals_list)
        lines._strx_sync_allocation_dates_from_line()
        return lines

    def write(self, vals):
        cabin_spec_changes = self._strx_prepare_confirmed_cabin_spec_changes(vals)
        self._strx_reject_confirmed_cabin_qty_increase(vals)
        self._strx_reject_qty_below_selected_serials(vals)
        res = super().write(vals)
        rental_period_updated = False
        if not self.env.context.get('strx_skip_rental_period_update') \
                and {'strx_rental_start_date', 'strx_rental_days'} & set(vals) \
                and 'strx_expected_return_date' not in vals:
            for line in self.filtered(lambda l: l.product_id.strx_is_cabin):
                if line.strx_rental_start_date and line.strx_rental_days:
                    super(
                        SaleOrderLine,
                        line.with_context(strx_skip_rental_period_update=True)
                    ).write({
                        'strx_expected_return_date': (
                            line.strx_rental_start_date + timedelta(
                                days=line.strx_rental_days)),
                    })
                    rental_period_updated = True
        if {'strx_rental_start_date', 'strx_rental_days',
                'strx_expected_return_date'} & set(vals) or rental_period_updated:
            self._strx_sync_allocation_dates_from_line()
        if cabin_spec_changes:
            self.browse(cabin_spec_changes)._strx_apply_confirmed_cabin_spec_changes(
                cabin_spec_changes)
        return res

    def _strx_reject_qty_below_selected_serials(self, vals):
        """Never let a later line edit make an existing allocation over-count."""
        if 'product_uom_qty' not in vals:
            return
        new_quantity = vals.get('product_uom_qty') or 0.0
        for line in self:
            active_allocations = line.strx_allocation_ids.filtered(
                lambda alloc: alloc.state not in (
                    'returned', 'available', 'done', 'cancel'))
            over_limit = active_allocations.filtered(
                lambda alloc: len(alloc.lot_ids) > new_quantity)
            if over_limit:
                raise UserError(_(
                    "The rental-line quantity cannot be reduced to %(quantity)s "
                    "because allocation %(allocation)s already has %(selected)s "
                    "selected serials. Remove serials from the allocation first.",
                    quantity=new_quantity,
                    allocation=over_limit[0].name,
                    selected=len(over_limit[0].lot_ids)))

    def _strx_is_cabin_product(self, product):
        return bool(product and product.strx_is_cabin)

    @api.onchange('product_id')
    def _onchange_strx_free_additional_service(self):
        for line in self:
            if line.product_id.strx_is_free_additional_service:
                line.price_unit = 0.0

    @api.onchange('product_id', 'strx_rental_start_date', 'strx_rental_days')
    def _onchange_strx_rental_period(self):
        for line in self:
            if not line.product_id.strx_is_cabin:
                continue
            if not line.strx_rental_start_date:
                line.strx_rental_start_date = line._strx_default_rental_start()
            if line.strx_rental_start_date and line.strx_rental_days:
                line.strx_expected_return_date = (
                    line.strx_rental_start_date + timedelta(
                        days=line.strx_rental_days))

    def _strx_default_rental_start(self):
        self.ensure_one()
        order_date = self.order_id.date_order
        return order_date.date() if order_date else fields.Date.context_today(self)

    def _strx_prepare_rental_period_vals(self, vals_list):
        for vals in vals_list:
            if vals.get('display_type') or not vals.get('product_id'):
                continue
            product = self.env['product.product'].browse(vals['product_id'])
            if not product.strx_is_cabin:
                continue
            start = vals.get('strx_rental_start_date')
            days = vals.get('strx_rental_days')
            if days and not start:
                order = self.env['sale.order'].browse(vals.get('order_id'))
                order_date = order.date_order.date() if order and order.date_order else False
                start = order_date or fields.Date.context_today(self)
                vals['strx_rental_start_date'] = start
            if start and days and not vals.get('strx_expected_return_date'):
                vals['strx_expected_return_date'] = (
                    fields.Date.to_date(start) + timedelta(days=days))

    def _strx_sync_allocation_dates_from_line(self):
        for line in self.filtered(lambda l: l.product_id.strx_is_cabin):
            values = {}
            if line.strx_rental_start_date:
                values['strx_date_out'] = line.strx_rental_start_date
            if line.strx_expected_return_date:
                values['strx_expected_return_date'] = line.strx_expected_return_date
            if not values:
                continue
            allocations = line.strx_allocation_ids.filtered(
                lambda a: a.state not in ('returned', 'available', 'done', 'cancel'))
            if allocations:
                allocations.write(values)

    def _strx_reject_confirmed_cabin_line_create(self, vals_list):
        """After confirmation, extra cabin quantity must be a new order.

        This is server-side on purpose: the button/wizard is the friendly path, but
        imports/RPC/manual line edits should not mutate the original commercial
        order either.
        """
        if self.env.context.get('strx_allow_confirmed_cabin_qty_change'):
            return
        for vals in vals_list:
            order_id = vals.get('order_id')
            product_id = vals.get('product_id')
            display_type = vals.get('display_type')
            if not order_id or not product_id or display_type:
                continue
            order = self.env['sale.order'].browse(order_id)
            product = self.env['product.product'].browse(product_id)
            qty = vals.get('product_uom_qty', 1.0) or 0.0
            if order.state in ('sale', 'done') and qty > 0 \
                    and self._strx_is_cabin_product(product):
                raise UserError(_(
                    "Confirmed rental orders cannot receive extra cabin quantity "
                    "on the same order. Create a quantity increase order instead."))

    def _strx_reject_confirmed_cabin_qty_increase(self, vals):
        if self.env.context.get('strx_allow_confirmed_cabin_qty_change'):
            return
        if not ({'product_uom_qty', 'product_id'} & set(vals)):
            return
        for line in self:
            if line.display_type or line.order_id.state not in ('sale', 'done'):
                continue
            product = self.env['product.product'].browse(
                vals.get('product_id')) if vals.get('product_id') else line.product_id
            if not self._strx_is_cabin_product(product):
                continue
            if vals.get('product_id') and not line.product_id.strx_is_cabin \
                    and line.product_uom_qty > 0:
                raise UserError(_(
                    "Confirmed rental orders cannot receive extra cabin quantity "
                    "on the same order. Create a quantity increase order instead."))
            new_qty = vals.get('product_uom_qty', line.product_uom_qty)
            precision = line.product_uom_id.rounding if line.product_uom_id else 0.01
            if float_compare(new_qty, line.product_uom_qty,
                             precision_rounding=precision) > 0:
                raise UserError(_(
                    "Confirmed rental orders cannot receive extra cabin quantity "
                    "on the same order. Create a quantity increase order instead."))

    def _strx_prepare_confirmed_cabin_spec_changes(self, vals):
        """Capture allowed confirmed-order cabin spec changes before write().

        Quantity additions remain blocked elsewhere. This route is only for a
        salesperson changing an existing cabin line from one cabin specification to
        another, then immediately warning logistics so open allocations/shipments
        cannot silently continue with the old serial.
        """
        if 'product_id' not in vals or self.env.context.get(
                'strx_skip_confirmed_cabin_spec_change_alert'):
            return {}
        new_product = self.env['product.product'].browse(vals.get('product_id'))
        changes = {}
        for line in self:
            if line.display_type or line.order_id.state not in ('sale', 'done'):
                continue
            old_product = line.product_id
            if not old_product.strx_is_cabin:
                continue
            if not new_product or not new_product.strx_is_cabin:
                raise UserError(_(
                    "Confirmed cabin rental lines can only be changed to another "
                    "cabin specification. Use a separate commercial process to "
                    "remove a cabin from a confirmed order."))
            if old_product == new_product:
                continue
            if line.order_id.locked or line.qty_invoiced > 0 or line.qty_delivered > 0:
                raise UserError(_(
                    "This cabin line is already locked, invoiced, or delivered. "
                    "Use the logistics substitution/return process instead."))
            if not (
                self.env.user.has_group('sales_team.group_sale_salesman')
                or self.env.user.has_group('sales_team.group_sale_manager')
            ):
                raise UserError(_(
                    "Only a Sales user can change the cabin specification on a "
                    "confirmed rental order."))
            changes[line.id] = old_product.id
        return changes

    def _strx_apply_confirmed_cabin_spec_changes(self, old_product_by_line):
        Activity = self.env['mail.activity']
        activity_type = self.env.ref('mail.mail_activity_data_todo',
                                     raise_if_not_found=False)
        if not activity_type:
            return
        users = self._strx_logistics_spec_change_users()
        Allocation = self.env['strx.cabin.allocation']

        for line in self:
            old_product = self.env['product.product'].browse(
                old_product_by_line.get(line.id))
            if not old_product or old_product == line.product_id:
                continue

            active_allocations = line.strx_allocation_ids.filtered(
                lambda alloc: alloc.state not in (
                    'returned', 'available', 'done', 'cancel'))
            reset_allocations = Allocation
            locked_allocations = Allocation
            released_lots = self.env['stock.lot']

            for alloc in active_allocations:
                if alloc.state in ('draft', 'allocated'):
                    old_lots = alloc.lot_ids
                    mismatched_lots = old_lots.filtered(
                        lambda lot: lot.product_id != line.product_id)
                    if mismatched_lots:
                        released_lots |= mismatched_lots
                        alloc._strx_release_lots(
                            reason_tmpl=_("Specification changed on %(ref)s"))
                        alloc.with_context(
                            strx_skip_confirmed_cabin_spec_change_alert=True,
                            strx_skip_return_alerts=True,
                        ).write({
                            'product_id': line.product_id.id,
                            'lot_ids': [(5, 0, 0)],
                            'state': 'draft',
                        })
                    else:
                        alloc.with_context(
                            strx_skip_confirmed_cabin_spec_change_alert=True,
                            strx_skip_return_alerts=True,
                        ).write({'product_id': line.product_id.id})
                    reset_allocations |= alloc
                else:
                    locked_allocations |= alloc

            shipping_orders = self._strx_open_shipping_orders_for_spec_change(
                line.order_id)
            if released_lots:
                for shipment in shipping_orders.filtered(
                        lambda ship: ship.state == 'draft'):
                    old_lots_on_shipment = shipment.lot_ids & released_lots
                    if old_lots_on_shipment:
                        shipment.with_context(strx_shipping_autofill_lots=True).write({
                            'lot_ids': [(3, lot.id) for lot in old_lots_on_shipment],
                        })

            self._strx_notify_logistics_cabin_spec_change(
                line=line,
                old_product=old_product,
                reset_allocations=reset_allocations,
                locked_allocations=locked_allocations,
                shipping_orders=shipping_orders,
                users=users,
                activity_type=activity_type,
                Activity=Activity,
            )

    def _strx_logistics_spec_change_users(self):
        group = self.env.ref('stock.group_stock_manager', raise_if_not_found=False)
        users = group.all_user_ids.filtered(lambda user: user.active) if group else self.env['res.users']
        if not users:
            group = self.env.ref('stock.group_stock_user', raise_if_not_found=False)
            users = group.all_user_ids.filtered(lambda user: user.active) if group else users
        dedicated_users = users.filtered(
            lambda user: user.login != 'admin'
            and user != self.env.ref('base.user_admin', raise_if_not_found=False))
        return dedicated_users or users or self.env.user

    def _strx_open_shipping_orders_for_spec_change(self, order):
        if 'strx.cabin.shipping.order' not in self.env:
            return self.env['ir.model']
        return self.env['strx.cabin.shipping.order'].search([
            ('order_id', '=', order.id),
            ('movement_type', 'in', ('delivery', 'site_transfer')),
            ('state', 'not in', ('delivered', 'cancel')),
        ])

    def _strx_spec_change_target_records(self, order, shipping_orders):
        targets = [order]
        targets.extend(shipping_orders)
        return targets

    def _strx_spec_change_texts(self, user, target, line, old_product,
                                reset_allocations, locked_allocations):
        # Addressed to `user`, so written in that user's language.
        env = self.with_context(lang=user.lang or self.env.lang).env
        if target._name == 'strx.cabin.shipping.order':
            ref = target.name or target.display_name
            summary = env._("Shipment %(ref)s — sales order product changed", ref=ref)
        else:
            ref = line.order_id.name or line.order_id.display_name
            summary = env._("Sales Order %(ref)s — cabin specification changed", ref=ref)

        body = [
            env._("Sales changed the cabin product/specification."),
            env._("Sales Order: %s") % (line.order_id.name or '-'),
            env._("Line: %s") % (line.name or line.display_name or '-'),
            env._("From: %s") % (old_product.display_name or '-'),
            env._("To: %s") % (line.product_id.display_name or '-'),
        ]
        reason = self.env.context.get('strx_spec_change_reason')
        if reason:
            body.append(env._("Reason: %s") % reason)
        if reset_allocations:
            body.append(
                env._("These allocations were reset to Draft and their old serials "
                      "were removed: %s")
                % ", ".join(reset_allocations.mapped('name')))
        if locked_allocations:
            body.append(
                env._("Warning: these allocations are already in an advanced stage "
                      "and need manual logistics review: %s")
                % ", ".join(locked_allocations.mapped('name')))
        body.append(env._("Review open allocations and shipments before dispatch."))
        return summary, "<br/>".join(body)

    def _strx_notify_logistics_cabin_spec_change(
            self, line, old_product, reset_allocations, locked_allocations,
            shipping_orders, users, activity_type, Activity):
        order = line.order_id
        deadline = self.env['strx.cabin.allocation']._strx_company_today(
            order.company_id)
        for target in self._strx_spec_change_target_records(order, shipping_orders):
            model = self.env['ir.model']._get(target._name)
            if not model:
                continue
            subject, body = self._strx_spec_change_texts(
                self.env.user, target, line, old_product,
                reset_allocations, locked_allocations)
            target.message_post(body=body, subject=subject, subtype_xmlid='mail.mt_note')
            for user in users:
                summary, note = self._strx_spec_change_texts(
                    user, target, line, old_product,
                    reset_allocations, locked_allocations)
                Activity.create({
                    'activity_type_id': activity_type.id,
                    'res_model_id': model.id,
                    'res_id': target.id,
                    'user_id': user.id,
                    'date_deadline': deadline,
                    'summary': summary,
                    'note': note,
                })

    def unlink(self):
        # allocation.order_line_id is ondelete='cascade' (a DB-level FK), so deleting a
        # line removes its allocations in PostgreSQL and BYPASSES the allocation's own
        # Python unlink(). Release the held serials here first, or they strand.
        self.strx_allocation_ids._strx_release_lots(
            reason_tmpl=_("Rental line of %(ref)s deleted"))
        return super().unlink()


# NOTE (Odoo 19): 'sale.order.option' and the Optional Products feature were
# removed from sale_management in Odoo 19. The guard that restricted that tab to
# products flagged strx_is_free_additional_service therefore has nothing left to
# guard and is gone with it. The flag itself stays in use on sale.order.line (see
# _onchange_strx_free_additional_service) and on the product form.

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    strx_allocation_ids = fields.One2many(
        'strx.cabin.allocation', 'order_id', string='Cabin Allocations')
    strx_allocation_count = fields.Integer(
        compute='_compute_strx_allocation_count')
    strx_origin_order_id = fields.Many2one(
        'sale.order', string='Original Order', copy=False, readonly=True,
        index=True)
    strx_addition_order_ids = fields.One2many(
        'sale.order', 'strx_origin_order_id', string='Quantity Increase Orders',
        readonly=True)
    strx_addition_order_count = fields.Integer(
        string='Quantity Increases', compute='_compute_strx_addition_order_count')

    def _compute_strx_allocation_count(self):
        for order in self:
            order.strx_allocation_count = len(order.strx_allocation_ids)

    def _compute_strx_addition_order_count(self):
        for order in self:
            order.strx_addition_order_count = len(order.strx_addition_order_ids)

    def _strx_assert_allocations_ready_for_invoice(self):
        """Require a committed serial for every ordered cabin unit.

        Only cabin products participate in allocation.  Sections, notes, down
        payments and ordinary/additional products keep Odoo's standard invoicing
        behaviour.
        """
        incomplete = []
        for order in self:
            cabin_lines = order.order_line.filtered(
                lambda line: not line.display_type
                and not line.is_downpayment
                and line.product_id.strx_is_cabin
                and line.product_uom_qty > 0)
            for line in cabin_lines:
                required = max(int(math.ceil(line.product_uom_qty or 0.0)), 0)
                committed = line._strx_committed_allocation_lots()
                if len(committed) != required:
                    incomplete.append(_(
                        "%(order)s — %(product)s: %(allocated)s/%(required)s "
                        "serials allocated",
                        order=order.name,
                        product=line.product_id.display_name,
                        allocated=len(committed),
                        required=required))
        if incomplete:
            raise UserError(_(
                "Cannot create the invoice until every cabin item is fully "
                "allocated.\n\n%(lines)s\n\nOpen Cabin Allocations, select all "
                "required serials, then click Allocate.",
                lines='\n'.join('- %s' % line for line in incomplete)))

    def _create_invoices(self, grouped=False, final=False, date=None):
        self._strx_assert_allocations_ready_for_invoice()
        return super()._create_invoices(grouped=grouped, final=final, date=date)

    def unlink(self):
        # Deleting an order DB-cascades to its lines AND allocations directly, bypassing
        # both sale.order.line.unlink() and allocation.unlink(). Release the serials here.
        self.strx_allocation_ids._strx_release_lots(
            reason_tmpl=_("Rental order of %(ref)s deleted"))
        return super().unlink()

    def action_view_strx_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cabin Allocations'),
            'res_model': 'strx.cabin.allocation',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def action_open_strx_quantity_increase_wizard(self):
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            raise UserError(_(
                "Quantity increases are only created from confirmed rental orders."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quantity Increase'),
            'res_model': 'strx.sale.quantity.increase.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_original_order_id': self.id},
        }

    def action_open_strx_product_change_wizard(self):
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            raise UserError(_(
                "Cabin product changes are only available on confirmed rental orders."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Change Cabin Product'),
            'res_model': 'strx.sale.product.change.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_original_order_id': self.id},
        }

    def action_view_strx_addition_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quantity Increase Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('strx_origin_order_id', '=', self.id)],
            'context': {'default_strx_origin_order_id': self.id},
        }
