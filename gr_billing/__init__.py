# -*- coding: utf-8 -*-
from . import models


def _backfill_rental_order_links(env):
    """Link legacy invoices that only carried the rental order reference text."""
    Order = env['gr.rental.order'].sudo()
    Move = env['account.move'].sudo()
    orders = Order.search([])
    if not orders:
        return

    order_by_key = {
        (order.name, order.company_id.id): order.id
        for order in orders
        if order.name
    }
    if not order_by_key:
        return
    moves = Move.search([
        ('rental_order_id', '=', False),
        ('move_type', 'in', ('out_invoice', 'out_refund')),
        ('invoice_origin', 'in', list({key[0] for key in order_by_key})),
        ('company_id', 'in', orders.company_id.ids),
    ])
    for move in moves:
        order_id = order_by_key.get((move.invoice_origin, move.company_id.id))
        if order_id:
            move.rental_order_id = order_id


def post_init_create_tax(env):
    """Ensure a 15% KSA sales VAT exists for each company, created via ORM so
    the chart-of-accounts/country dependencies resolve correctly. Idempotent:
    skips companies that already have a matching 15% sale tax."""
    Tax = env['account.tax']
    TaxGroup = env['account.tax.group']
    for company in env['res.company'].search([]):
        existing = Tax.with_company(company).search([
            ('company_id', '=', company.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 15.0),
        ], limit=1)
        if existing:
            continue
        # account.tax.country_id is required in Odoo 19 and computes from the
        # company's fiscal country. Without one there is no valid tax to
        # create, so leave it to the accounting setup.
        country = company.account_fiscal_country_id or company.country_id
        if not country:
            continue
        # account.tax.tax_group_id is required, and its compute only picks up a
        # group that already exists. A company with no chart of accounts has
        # none, so create one instead of letting the INSERT fail.
        tax_group = TaxGroup.with_company(company).search([
            ('company_id', '=', company.id),
        ], limit=1)
        try:
            # Savepoint: a failed INSERT would otherwise abort the whole
            # module-installation transaction, not just this company.
            with env.cr.savepoint():
                if not tax_group:
                    tax_group = TaxGroup.with_company(company).create({
                        'name': 'VAT 15%',
                        'company_id': company.id,
                    })
                Tax.with_company(company).create({
                    'name': 'VAT 15% (Sales)',
                    'amount': 15.0,
                    'amount_type': 'percent',
                    'type_tax_use': 'sale',
                    'company_id': company.id,
                    'country_id': country.id,
                    'tax_group_id': tax_group.id,
                })
        except Exception:
            # If accounting isn't fully configured for this company yet, skip;
            # the billing run has a runtime fallback and a clear error message.
            continue
    _backfill_rental_order_links(env)
