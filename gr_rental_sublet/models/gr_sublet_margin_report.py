# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools


class GrSubletMarginReport(models.Model):
    """Read-only pivot source for margin analysis. One row per rent-out order,
    carrying the owner dimension so owned-fleet margin and sublet margin split
    cleanly, plus the rent-in cost and invoiced revenue for that order."""
    _name = 'gr.sublet.margin.report'
    _description = 'Sublet / Fleet Margin Analysis'
    _auto = False
    _order = 'order_date desc'

    order_id = fields.Many2one('gr.rental.order', string='Rent-out Order', readonly=True)
    asset_id = fields.Many2one('gr.generator.asset', string='Equipment', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    owner_type = fields.Selection([
        ('owned', 'Owned Fleet'),
        ('rented_in', 'Sublet (Rented-in)'),
        ('customer_owned', 'Customer-owned'),
    ], string='Fleet Type', readonly=True)
    agreement_id = fields.Many2one('gr.sublet.agreement', string='Sublet Agreement', readonly=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', readonly=True)
    order_date = fields.Date(string='Order Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    revenue_out = fields.Monetary(string='Revenue Out', currency_field='currency_id', readonly=True)
    cost_in = fields.Monetary(string='Cost In', currency_field='currency_id', readonly=True)
    extra_direct_cost = fields.Monetary(
        string='Extra Direct Cost', currency_field='currency_id', readonly=True)
    total_cost = fields.Monetary(
        string='Total Cost', currency_field='currency_id', readonly=True)
    margin = fields.Monetary(string='Margin', currency_field='currency_id', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    o.id                        AS id,
                    o.id                        AS order_id,
                    o.asset_id                  AS asset_id,
                    o.partner_id                AS partner_id,
                    a.owner_type                AS owner_type,
                    o.sublet_agreement_id       AS agreement_id,
                    sa.vendor_id                AS vendor_id,
                    o.create_date::date         AS order_date,
                    o.company_id                AS company_id,
                    c.currency_id               AS currency_id,
                    COALESCE(rev.revenue, 0.0)  AS revenue_out,
                    CASE WHEN first_ord.first_order_id = o.id
                         THEN COALESCE(sa.rent_in_amount, 0.0) ELSE 0.0 END AS cost_in,
                    COALESCE(dc_order.extra_cost, 0.0)
                      + CASE WHEN first_ord.first_order_id = o.id
                             THEN COALESCE(dc_agreement.extra_cost, 0.0) ELSE 0.0 END
                                                 AS extra_direct_cost,
                    CASE WHEN first_ord.first_order_id = o.id
                         THEN COALESCE(sa.rent_in_amount, 0.0) ELSE 0.0 END
                      + COALESCE(dc_order.extra_cost, 0.0)
                      + CASE WHEN first_ord.first_order_id = o.id
                             THEN COALESCE(dc_agreement.extra_cost, 0.0) ELSE 0.0 END
                                                 AS total_cost,
                    COALESCE(rev.revenue, 0.0)
                      - CASE WHEN first_ord.first_order_id = o.id
                             THEN COALESCE(sa.rent_in_amount, 0.0) ELSE 0.0 END
                      - COALESCE(dc_order.extra_cost, 0.0)
                      - CASE WHEN first_ord.first_order_id = o.id
                             THEN COALESCE(dc_agreement.extra_cost, 0.0) ELSE 0.0 END
                                                 AS margin
                FROM gr_rental_order o
                JOIN gr_generator_asset a  ON a.id = o.asset_id
                JOIN res_company c         ON c.id = o.company_id
                LEFT JOIN gr_sublet_agreement sa ON sa.id = o.sublet_agreement_id
                LEFT JOIN (
                    SELECT sublet_agreement_id, MIN(id) AS first_order_id
                    FROM gr_rental_order
                    WHERE sublet_agreement_id IS NOT NULL
                    GROUP BY sublet_agreement_id
                ) first_ord ON first_ord.first_order_id = o.id
                LEFT JOIN (
                    SELECT
                        m.invoice_origin AS origin,
                        COALESCE(
                            SUM(m.amount_untaxed) FILTER (WHERE m.state = 'posted'),
                            SUM(m.amount_untaxed) FILTER (WHERE m.state != 'cancel'),
                            0.0
                        ) AS revenue
                    FROM account_move m
                    WHERE m.move_type = 'out_invoice'
                    GROUP BY m.invoice_origin
                ) rev ON rev.origin = o.name
                LEFT JOIN (
                    SELECT rental_order_id, SUM(amount) AS extra_cost
                    FROM gr_sublet_direct_cost
                    WHERE rental_order_id IS NOT NULL
                    GROUP BY rental_order_id
                ) dc_order ON dc_order.rental_order_id = o.id
                LEFT JOIN (
                    SELECT agreement_id, SUM(amount) AS extra_cost
                    FROM gr_sublet_direct_cost
                    WHERE rental_order_id IS NULL
                    GROUP BY agreement_id
                ) dc_agreement ON dc_agreement.agreement_id = sa.id
            )
        """ % self._table)
