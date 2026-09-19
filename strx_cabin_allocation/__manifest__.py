# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Allocation',
    'version': '19.0.1.0.0',
    'summary': 'Commit an exact serialised cabin to a rental order line, with '
               'specification-match and no-overlap enforcement.',
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    # Community-only. 'sale' carries the rental order; NO sale_renting (Enterprise).
    'depends': [
        'strx_cabin_security',
        'strx_cabin_base', 'sale', 'sale_management', 'stock', 'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/cabin_record_rules.xml',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/stock_lot_picker_views.xml',
        'views/cabin_allocation_views.xml',
        'views/quantity_increase_wizard_views.xml',
        'views/product_change_wizard_views.xml',
        'views/return_assessment_wizard_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'views/report_invoice.xml',
        'views/cabin_allocation_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'strx_cabin_allocation/static/src/serial_picker/serial_picker.js',
            'strx_cabin_allocation/static/src/serial_picker/serial_picker.xml',
            'strx_cabin_allocation/static/src/serial_picker/serial_picker.scss',
        ],
    },
    'installable': True,
    'application': False,
}
