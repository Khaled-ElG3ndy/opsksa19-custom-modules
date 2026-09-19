# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Sublet Rental Margin",
    'summary': "Rent-in PO vs rent-out order per unit; owned-fleet vs sublet "
               "margin; vendor-payable exposure surfacing",
    'description': "Sublet rental margin (gr.sublet.agreement). ABSAL rents "
                   "generators IN from third-party vendors and rents them OUT to "
                   "customers on the same shared fleet. A sublet agreement owns "
                   "the rent-in side: the vendor, the rent-in purchase order "
                   "(born linked the M12 way), the period ABSAL is on the hook, "
                   "and the rent-in cost. Rental orders for the same physical "
                   "unit (by Asset No / serial) are the rent-out side. Margin is "
                   "cost-in (from the PO) vs revenue-out (from the unit's "
                   "invoiced rentals), reported in a native pivot sliced by unit, "
                   "customer, period, and owner type - so owned-fleet margin and "
                   "sublet margin separate cleanly. Vendor-payable exposure (the "
                   "rent-in obligation still live while the unit is still out with "
                   "a customer, or returned late) is a computed flag surfaced in a "
                   "dedicated Sublet Exposure menu. Uses the M11 owner flag "
                   "(rented_in -> owner_partner_id is the vendor). Part of the "
                   "Generator Rental ERP vertical (gr_* suite) for Odoo 18 "
                   "Community.",
    'version': '19.0.1.2.1',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_rental_order',
                'gr_equipment', 'gr_parts_purchase', 'gr_rental_inspection',
                'gr_billing', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_sublet_rules.xml',
        'data/ir_sequence.xml',
        'data/gr_sublet_cron.xml',
        'data/gr_sublet_buffer_params.xml',
        'views/gr_sublet_agreement_views.xml',
        'views/gr_generator_asset_sublet_views.xml',
        'views/gr_sublet_margin_views.xml',
        'views/gr_sublet_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
