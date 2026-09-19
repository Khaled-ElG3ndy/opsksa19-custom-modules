# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        """Primary hard-stop: the exact allocated serial of the correct specification
        must be what leaves the yard. Runs BEFORE the transfer is validated, so a wrong
        unit can never be dispatched — and, unlike create/write, this pass requires an
        allocation to exist (no_alloc is a violation here)."""
        for picking in self:
            violations = []
            for line in picking.move_line_ids:
                # Only lines that will actually move (done quantity > 0).
                if line.quantity <= 0:
                    continue
                violation = line._strx_dispatch_violation(require_allocation=True)
                if violation:
                    violations.append(violation)
            if violations:
                # Raise via the picking's move lines to reuse the translated formatter.
                picking.move_line_ids[:1]._strx_raise_block(violations)
        return super().button_validate()
