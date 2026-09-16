# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    """Hold the customer that every new order of this Point of Sale starts with."""
    _inherit = 'pos.config'

    default_customer_id = fields.Many2one(
        'res.partner',
        string="Default Customer",
        check_company=True,
        ondelete='set null',
        help="Customer preselected on every order created in this Point of "
             "Sale. The cashier can still change it or clear it on any "
             "individual order.",
    )

    def get_limited_partners_loading(self, offset=0):
        """Pull the default customer into the limited set of loaded partners.

        This is the hook core itself uses to build the ``res.partner`` domain,
        so honouring it keeps the customer in the session for a stock database.
        It is not enough on its own -- another module may AND a further
        restriction onto that domain -- which is why
        :meth:`~.ResPartner._load_pos_data_search_read` also guarantees it.
        """
        partner_ids = super().get_limited_partners_loading(offset)
        default_customer = self.default_customer_id
        if default_customer and (default_customer.id,) not in partner_ids:
            partner_ids.append((default_customer.id,))
        return partner_ids
