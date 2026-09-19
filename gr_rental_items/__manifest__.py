# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Rent Any Asset (Items & Accessories)",
    'summary': "Rent cables, fuel tanks, distribution panels and any other asset - "
               "standalone or bundled with a generator, each priced or free",
    'description': "Rent any asset (meeting requirement 1). Rentals are no longer "
                   "limited to generators. A maintainable catalogue of rentable "
                   "ITEM TYPES (cable, fuel tank, distribution panel, and any "
                   "other type the client adds from the UI) each has individual "
                   "physical UNITS that are tracked and cannot be double-booked. "
                   "A rental order can now carry any number of item lines "
                   "ALONGSIDE a generator (bundled - each line priced or FREE with "
                   "the generator), or WITHOUT any generator at all (standalone - "
                   "e.g. the customer rents only a distribution panel). Line "
                   "pricing is independent per item. Part of the Generator Rental "
                   "ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.5',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_equipment',
                'gr_rental_order', 'gr_rental_inspection'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_rental_items_rules.xml',
        'data/ir_sequence.xml',
        'data/gr_rental_item_data.xml',
        'views/gr_rental_item_views.xml',
        'views/gr_rental_order_items_views.xml',
        'views/gr_rental_item_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
