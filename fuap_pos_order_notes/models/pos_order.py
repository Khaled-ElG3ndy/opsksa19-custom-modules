# -*- coding: utf-8 -*-
from markupsafe import Markup, escape

from odoo import fields, models


def _plain_text_to_html(value):
    """Return safe HTML for the HTML fields used by pickings and invoices."""
    if not value:
        return False
    return Markup("<br>").join(escape(line) for line in value.splitlines())


class PosOrder(models.Model):
    _inherit = "pos.order"

    order_note = fields.Text(
        string="Order Note",
        tracking=True,
        help="Note for the complete POS order. It can be printed on the receipt "
             "and copied to the delivery note and invoice.",
    )

    def _prepare_invoice_vals(self):
        vals = super()._prepare_invoice_vals()
        notes = [note.strip() for note in self.mapped("order_note") if note and note.strip()]
        if notes:
            vals["narration"] = _plain_text_to_html("\n".join(notes))
        return vals

    def _create_order_picking(self):
        result = super()._create_order_picking()
        self._sync_order_note_to_documents(sync_invoice=False)
        return result

    def write(self, vals):
        result = super().write(vals)
        if "order_note" in vals:
            self._sync_order_note_to_documents()
        return result

    def _sync_order_note_to_documents(self, sync_invoice=True):
        """Keep backend edits consistent with already-created documents."""
        for order in self:
            if order.picking_ids:
                order.picking_ids.write({"note": _plain_text_to_html(order.order_note)})

        if sync_invoice:
            for invoice in self.mapped("account_move"):
                notes = [
                    note.strip()
                    for note in invoice.pos_order_ids.mapped("order_note")
                    if note and note.strip()
                ]
                invoice.narration = _plain_text_to_html("\n".join(notes)) if notes else False

