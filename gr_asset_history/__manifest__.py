# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Asset Full History",
    'summary': "Central lifetime history for generators and rentable item units",
    'description': "Adds a structured Asset History ledger for each generator "
                   "asset and rentable item unit. The ledger is populated from "
                   "rental, delivery, return, maintenance, inspection, field "
                   "worksheet, parts, contract, and sublet workflows without "
                   "replacing the existing chatter.",
    'version': '19.0.1.0.2',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': [
        'gr_security_base',
        'gr_equipment',
        'gr_rental_items',
        'gr_rental_order',
        'gr_contract',
        'gr_maintenance',
        'gr_rental_inspection',
        'gr_field_worksheet',
        'gr_parts_consumption',
        'gr_rental_sublet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_asset_history_rules.xml',
        'views/rental_asset_history_views.xml',
        'views/gr_generator_asset_history_views.xml',
        'views/gr_rental_item_history_views.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
