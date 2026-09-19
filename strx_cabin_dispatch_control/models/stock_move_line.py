# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import UserError

# Allocation states in which a serial is actually committed to a rental. 'draft' is
# not yet approved; 'cancel'/'done' no longer hold the unit. Kept here so the checker
# and any later module agree on what "approved" means.
COMMITTED_ALLOC_STATES = ('allocated', 'dispatched', 'on_rent', 'returned')

# Context flag for auditable, deliberate bypass by trusted server code (e.g. a future
# substitution-approval flow that re-points the allocation then re-reserves). NEVER set
# from a UI action — it is not a user-facing escape hatch.
BYPASS_KEY = 'strx_bypass_dispatch_control'

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # ------------------------------------------------------------------ scope
    def _strx_is_controlled_dispatch(self):
        """True only for a controlled cabin asset leaving the yard to a customer.

        This is the single gate that keeps ordinary transfers untouched: a non-cabin
        product, or a cabin on an internal / incoming move, returns False immediately.
        """
        self.ensure_one()
        product = self.product_id
        if not product or not product.strx_is_cabin:
            return False
        # Outgoing dispatch = delivery picking type OR a customer destination.
        picking_type = self.picking_id.picking_type_id
        is_outgoing = picking_type.code == 'outgoing'
        to_customer = self.location_dest_id.usage == 'customer'
        return is_outgoing or to_customer

    def _strx_rental_order(self):
        """The sale order this move line is fulfilling, if any."""
        self.ensure_one()
        return self.move_id.sale_line_id.order_id or self.picking_id.sale_id

    def _strx_approved_allocations(self, order):
        return order.strx_allocation_ids.filtered(
            lambda a: a.lot_ids and a.state in COMMITTED_ALLOC_STATES)

    # --------------------------------------------------------------- checker
    def _strx_dispatch_violation(self, require_allocation):
        """Return a violation dict for this line, or None if it is fine / out of scope.

        require_allocation:
          - True  (transfer validation): a controlled cabin with no approved allocation
                  is itself a violation ('no_alloc') — the hard-stop on dispatch.
          - False (move-line create/write): if the order has NO approved allocation yet,
                  DEFER (return None) so ordinary reservation before allocation is not
                  broken. Once an allocation exists, a mismatching (spec or serial) line
                  is blocked — this is what closes the edit / barcode-injection back-door.
        """
        self.ensure_one()
        # Bypass is honored ONLY when the key is set AND we are in superuser mode.
        # A client RPC can forge the context key, but it cannot forge env.su — only
        # server code calling .sudo() (the substitution apply) can. So the key alone,
        # supplied by any user-controlled context, never passes the hard-stop.
        if self.env.context.get(BYPASS_KEY) and self.env.su:
            return None
        if not self._strx_is_controlled_dispatch():
            return None

        order = self._strx_rental_order()
        approved = self._strx_approved_allocations(order) if order \
            else self.env['strx.cabin.allocation']

        # A serial-tracked dispatch with no serial yet: let Odoo's own "serial required"
        # rule handle it — nothing to compare.
        if not self.lot_id:
            return None

        # OK: this exact (specification, serial) is an approved allocation.
        if approved.filtered(lambda a: a.product_id == self.product_id
                             and self.lot_id in a.lot_ids):
            return None

        if not approved:
            if require_allocation:
                return self._strx_make_violation('no_alloc', order, approved)
            return None  # defer to validation-time

        kind = 'wrong_spec' if self.product_id not in approved.mapped('product_id') \
            else 'wrong_serial'
        return self._strx_make_violation(kind, order, approved)

    def _strx_make_violation(self, kind, order, approved):
        self.ensure_one()
        return {
            'kind': kind,
            'order': order,
            'approved': approved,
            'scanned_product': self.product_id,
            'scanned_lot': self.lot_id,
        }

    # -------------------------------------------------------------- message
    @staticmethod
    def _strx_spec_serial(product, lot):
        spec = product.strx_cabin_spec or product.display_name
        serial = lot.name if lot else '—'
        code = product.default_code or '—'
        return spec, serial, code

    def _strx_raise_block(self, violations):
        """Compose the block message in the current user's language."""
        kinds = {v['kind'] for v in violations}
        # Required side: the order's approved serials (empty on 'no_alloc').
        approved = violations[0]['approved']
        required_lines = [
            "  • %s (%s / %s)" % self._strx_spec_serial(a.product_id, lot)
            for a in approved
            for lot in a.lot_ids
        ] or ["  • —"]
        scanned_lines = [
            "  • %s (%s / %s)" % self._strx_spec_serial(v['scanned_product'], v['scanned_lot'])
            for v in violations
        ]

        if 'wrong_spec' in kinds:
            title = _("Dispatch blocked — wrong specification.")
        elif 'wrong_serial' in kinds:
            title = _("Dispatch blocked — serial not approved for this rental.")
        else:  # no_alloc
            title = _("Dispatch blocked — no cabin allocated to this rental.")

        remedy = _("Scan an approved unit, re-allocate the correct serial, or raise a "
                   "substitution request.")

        req_hdr = _("Required")
        scan_hdr = _("Scanned")

        msg = "\n".join([
            title,
            "%s:" % req_hdr, *required_lines,
            "%s:" % scan_hdr, *scanned_lines,
            remedy,
        ])
        raise UserError(msg)

    # ------------------------------------------------------- create / write
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # Back-door #1: injecting a WRONG-SPEC move line (e.g. Barcode scan of a
        # different-product serial) onto an outgoing cabin transfer. Only 'wrong_spec'
        # is blocked here; a correct-spec/wrong-serial line is left to button_validate,
        # so ordinary auto-reservation is never blocked.
        violations = [v for v in (l._strx_dispatch_violation(require_allocation=False)
                                  for l in lines) if v and v['kind'] == 'wrong_spec']
        if violations:
            lines._strx_raise_block(violations)
        return lines

    def write(self, vals):
        res = super().write(vals)
        # Back-door #2: editing product_id / destination on an already-confirmed picking
        # to a different specification. Same softening: only 'wrong_spec' blocks here;
        # a wrong serial of the correct spec is caught at validation, not at reservation.
        if {'lot_id', 'product_id', 'location_dest_id'} & set(vals):
            violations = [v for v in (l._strx_dispatch_violation(require_allocation=False)
                                      for l in self) if v and v['kind'] == 'wrong_spec']
            if violations:
                self._strx_raise_block(violations)
        return res
