# -*- coding: utf-8 -*-
from odoo import api, models


class ResPartner(models.Model):
    """Make sure the Point of Sale default customer reaches the session."""
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_search_read(self, data, config):
        """Append the default customer to the partners sent to the session.

        A Point of Sale only loads a capped, most-used slice of the address
        book, and modules such as ``pos_customer_restrict`` narrow it further
        by ANDing their own condition onto the domain. Appending the record
        after the search instead of widening the domain means the default
        customer is loaded whatever those other modules decide, and in
        whichever order their overrides happen to run.

        Reading goes through :meth:`_load_pos_data_read`, so a customer the
        session user may not read is still left out.
        """
        records = super()._load_pos_data_search_read(data, config)
        default_customer = config.default_customer_id
        if not default_customer:
            return records
        if any(record['id'] == default_customer.id for record in records):
            return records
        return records + self._load_pos_data_read(default_customer, config)
