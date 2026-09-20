# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Dashboard',
    'version': '19.0.1.1.0',
    'summary': 'Modern operational dashboard for cabin availability, rentals, '
               'returns, allocations, substitutions and shipping.',
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    'depends': [
        'strx_cabin_security',
        'web',
        'strx_cabin_base',
        'strx_cabin_allocation',
        'strx_cabin_dispatch_control',
        'strx_cabin_shipping',
        'strx_cabin_substitution',
    ],
    'data': [
        'views/cabin_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'strx_cabin_dashboard/static/src/dashboard/cabin_dashboard.js',
            'strx_cabin_dashboard/static/src/dashboard/cabin_dashboard.xml',
            'strx_cabin_dashboard/static/src/dashboard/cabin_dashboard.scss',
            'strx_cabin_dashboard/static/src/theme/cabin_control_theme.scss',
        ],
    },
    'installable': True,
    'application': False,
}
