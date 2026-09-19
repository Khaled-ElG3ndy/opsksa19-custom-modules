# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Dispatch Hard-Stop',
    'version': '19.0.1.0.0',
    'summary': 'Server-side enforcement that the exact allocated serial of the correct '
               'specification is what leaves the yard. Blocks at transfer validation '
               'and on move-line create/write.',
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    # Community-only. sale_stock is the Community sale<->stock bridge (move.sale_line_id,
    # picking.sale_id) — NOT Enterprise. No sale_renting / stock_barcode dependency.
    'depends': [
        'strx_cabin_security','strx_cabin_allocation', 'sale_stock', 'stock'],
    'data': [],
    'installable': True,
    'application': False,
}
