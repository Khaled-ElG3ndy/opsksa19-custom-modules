# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RentalAssetRentalHistory(models.Model):
    _name = 'rental.asset.rental.history'
    _description = 'Asset Rental History Line'
    _order = 'start_datetime desc, id desc'
    _rec_name = 'rental_order_id'

    asset_id = fields.Many2one(
        'gr.generator.asset', string='Asset', required=True, index=True,
        ondelete='cascade')
    rental_order_id = fields.Many2one(
        'gr.rental.order', string='Rental Order', required=True, index=True,
        ondelete='cascade')
    order_line_id = fields.Many2one(
        'gr.rental.order.line', string='Order Line', index=True,
        ondelete='set null')
    asset_role = fields.Selection([
        ('main', 'Main Asset'),
        ('accessory', 'Accessory'),
    ], string='Role', required=True, default='main', index=True)
    partner_id = fields.Many2one('res.partner', string='Customer', index=True)
    contract_id = fields.Many2one(
        'gr.rental.contract', string='Contract', index=True)
    site_id = fields.Many2one('gr.customer.site', string='Site', index=True)
    start_datetime = fields.Datetime(string='Start Date', index=True)
    planned_return_datetime = fields.Datetime(string='Planned Return')
    actual_return_datetime = fields.Datetime(string='Actual Return')
    duration_days = fields.Float(
        string='Days', compute='_compute_duration_days', store=True)
    daily_rate = fields.Monetary(
        string='Daily Rate', currency_field='currency_id')
    revenue_amount = fields.Monetary(
        string='Revenue', currency_field='currency_id')
    is_free = fields.Boolean(string='Free of Charge')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('reserved', 'Reserved'),
        ('dispatched', 'Dispatched'),
        ('installed', 'Installed'),
        ('on_rent', 'On Rent'),
        ('off_hire_requested', 'Off-Hire Requested'),
        ('returned', 'Returned'),
        ('inspection', 'Inspection'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', index=True)
    technical_key = fields.Char(
        string='Technical Key', required=True, copy=False, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)

    _technical_key_company_uniq = models.Constraint(
        'unique(technical_key, company_id)',
        "This asset rental history line already exists for this company.",
    )

    @api.depends('start_datetime', 'actual_return_datetime',
                 'planned_return_datetime')
    def _compute_duration_days(self):
        for line in self:
            start = line.start_datetime
            end = line.actual_return_datetime or line.planned_return_datetime
            if not start or not end or end < start:
                line.duration_days = 0.0
                continue
            seconds = (end - start).total_seconds()
            line.duration_days = seconds / 86400.0

    @api.model
    def _technical_key(self, order, asset, role, order_line=False):
        line_part = order_line.id if order_line else 0
        return 'gr.rental.order:%s:rental_history:%s:%s:%s' % (
            order.id, role, asset.id, line_part)

    @api.model
    def _prepare_from_order_asset(self, order, asset, role, order_line=False):
        start_datetime = (
            order.actual_install_datetime
            or order.actual_dispatch_datetime
            or order.date_requested)
        if order_line:
            daily_rate = order_line.daily_rate or 0.0
            revenue = order_line.line_total or 0.0
            is_free = order_line.is_free
        else:
            daily_rate = (
                asset.rental_daily_rate
                or order.contract_id.base_daily_rate
                or 0.0)
            is_free = False
            end = order.actual_return_datetime or order.planned_return_datetime
            if start_datetime and end and end >= start_datetime:
                revenue = daily_rate * (
                    (end - start_datetime).total_seconds() / 86400.0)
            else:
                revenue = 0.0
        return {
            'asset_id': asset.id,
            'rental_order_id': order.id,
            'order_line_id': order_line.id if order_line else False,
            'asset_role': role,
            'partner_id': order.partner_id.id,
            'contract_id': order.contract_id.id,
            'site_id': order.site_id.id,
            'start_datetime': start_datetime,
            'planned_return_datetime': order.planned_return_datetime,
            'actual_return_datetime': order.actual_return_datetime,
            'daily_rate': daily_rate,
            'revenue_amount': revenue,
            'is_free': is_free,
            'state': order.state,
            'technical_key': self._technical_key(order, asset, role, order_line),
            'company_id': asset.company_id.id,
        }

    @api.model
    def sync_from_order(self, order):
        records = self.browse()
        for asset, role, order_line in order._asset_rental_history_targets():
            vals = self._prepare_from_order_asset(order, asset, role, order_line)
            existing = self.search([
                ('technical_key', '=', vals['technical_key']),
                ('company_id', '=', vals['company_id']),
            ], limit=1)
            if existing:
                existing.write(vals)
                records |= existing
            else:
                records |= self.create(vals)
        return records

    def action_open_rental_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.rental_order_id.display_name,
            'res_model': 'gr.rental.order',
            'res_id': self.rental_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
