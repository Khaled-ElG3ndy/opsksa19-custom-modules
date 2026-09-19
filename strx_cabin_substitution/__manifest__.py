# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Substitution Workflow',
    'version': '19.0.1.0.0',
    'summary': 'The only sanctioned route past the dispatch hard-stop: a controlled, '
               'priced, approved specification-change request that re-points the '
               'allocation and lets the approved serial through — server-side only.',
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    # Depends on the hard-stop module (for the BYPASS_KEY constant + enforcement it
    # overrides) and allocation. All Community.
    'depends': [
        'strx_cabin_security','strx_cabin_dispatch_control', 'strx_cabin_allocation', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'security/cabin_record_rules.xml',
        'data/ir_sequence_data.xml',
        'views/cabin_substitution_views.xml',
        'views/cabin_substitution_menus.xml',
    ],
    'installable': True,
    'application': False,
}
