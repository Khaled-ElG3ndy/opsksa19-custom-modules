# -*- coding: utf-8 -*-
from odoo import api, models


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    @api.model
    def default_get(self, fields_list):
        """Fail as soon as the Create Invoice action opens.

        The final check is repeated by ``_create_invoices`` and by
        ``sale.order._create_invoices``.  This early check is the friendly UI path;
        the repeated checks protect imports, RPC calls and custom integrations.
        """
        active_ids = self.env.context.get('active_ids') or []
        if active_ids:
            self.env['sale.order'].browse(active_ids)._strx_assert_allocations_ready_for_invoice()
        return super().default_get(fields_list)

    def _create_invoices(self, sale_orders):
        sale_orders._strx_assert_allocations_ready_for_invoice()
        return super()._create_invoices(sale_orders)
