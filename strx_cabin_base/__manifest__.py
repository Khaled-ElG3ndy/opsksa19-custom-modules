# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Base',
    'version': '19.0.1.1.0',
    'summary': 'Foundation for cabin-rental fulfillment control: cabin specifications, '
               'serialised asset readiness states and event-driven readiness history.',
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    # Community-only dependencies. NO Enterprise modules (sale_renting, stock_barcode,
    # sign, quality) — those are detected at runtime by later modules, never declared here.
    'depends': [
        'strx_cabin_security', 'base', 'product', 'stock', 'mail'],
    'external_dependencies': {
        'python': ['qrcode'],
    },
    'data': [
        'security/ir.model.access.csv',
        'security/cabin_record_rules.xml',
        'data/additional_service_products.xml',
        'views/product_template_views.xml',
        'views/stock_lot_views.xml',
        'views/readiness_log_views.xml',
        'views/cabin_card_wizard_views.xml',
        'views/report_cabin_card.xml',
        'views/strx_cabin_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'strx_cabin_base/static/src/cabin_card/cabin_card.scss',
        ],
    },
    'installable': True,
    'application': False,
}
