# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class GrRentalOrderReturnInfoWizard(models.TransientModel):
    """Read-only summary opened from the rental order's return smart button.

    Shows the rental start date, the expected return date, the current date
    (user timezone) and the computed remaining / overdue days together with
    the rental status. Only a snapshot at open time, so no separate action /
    window with useless empty content is created.
    """
    _name = 'gr.rental.order.return.info.wizard'
    _description = 'Rental Order Expected Return Info'

    order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', required=True, readonly=True)
    order_reference = fields.Char(
        related='order_id.name', string='Order Reference', readonly=True)
    rental_start_date = fields.Date(
        string='Rental Start Date', readonly=True,
        help="Actual install date, falling back to the actual dispatch date.")
    expected_return_date = fields.Date(
        string='Expected Return Date', readonly=True)
    current_date = fields.Date(string='Current Date', readonly=True)
    remaining_days = fields.Char(
        string='Remaining / Overdue Days', readonly=True)
    return_status = fields.Char(string='Status', readonly=True)
    rental_status = fields.Selection(
        related='order_id.state', string='Rental Status', readonly=True)

    @api.model
    def default_get(self, field_list):
        res = super().default_get(field_list)
        order = self.env['gr.rental.order'].browse(
            res.get('order_id'))
        if not order:
            order = self.env['gr.rental.order'].browse(
                self.env.context.get('default_order_id'))
        if order:
            res['order_id'] = order.id
            for dt_field in ('actual_install_datetime',
                             'actual_dispatch_datetime'):
                dt = order[dt_field]
                if dt:
                    res['rental_start_date'] = (
                        fields.Datetime.context_timestamp(order, dt).date())
                    break
            if order.planned_return_datetime:
                res['expected_return_date'] = (
                    fields.Datetime.context_timestamp(
                        order, order.planned_return_datetime).date())
            res['current_date'] = fields.Date.context_today(order)
            res['remaining_days'] = order.rental_return_primary
            res['return_status'] = order.rental_return_secondary
        return res