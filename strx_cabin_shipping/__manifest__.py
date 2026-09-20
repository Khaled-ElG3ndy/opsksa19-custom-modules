# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Shipping',
    'version': '19.0.1.1.0',
    'summary': 'Broker master and shipment: driver, vehicle, route, '
               'cost and dates, linked to the rental order and the exact serials carried.',
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    'depends': [
        'strx_cabin_security','strx_cabin_allocation', 'sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'security/cabin_record_rules.xml',
        'data/ir_sequence_data.xml',
        'views/cabin_broker_views.xml',
        'views/cabin_broker_payment_views.xml',
        'views/cabin_shipping_order_views.xml',
        'views/cabin_history_views.xml',
        'views/cabin_allocation_views.xml',
        'views/sale_order_views.xml',
        'views/cabin_shipping_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'strx_cabin_shipping/static/src/shipping/agreed_cost_field.js',
            'strx_cabin_shipping/static/src/shipping/agreed_cost_field.xml',
            'strx_cabin_shipping/static/src/shipping/receipt_attachment_preview_field.js',
            'strx_cabin_shipping/static/src/shipping/receipt_attachment_preview_field.xml',
            'strx_cabin_shipping/static/src/shipping/receipt_attachment_preview_field.scss',
            'strx_cabin_shipping/static/src/shipping/shipping_form.scss',
        ],
        'web.assets_unit_tests': [
            'strx_cabin_shipping/static/tests/**/*.test.js',
        ],
    },
    'installable': True,
    'application': False,
}
