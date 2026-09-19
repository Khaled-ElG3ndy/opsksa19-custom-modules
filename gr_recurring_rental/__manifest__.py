# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Recurring Rentals",
    'summary': "Remember which customers rent monthly, remind the team, and "
               "prepare the next rental order as a draft",
    'description': "Recurring customer rentals (gr.recurring.rental). Some "
                   "customers take roughly the same equipment every month, and "
                   "today somebody has to remember who they are and rebuild "
                   "the order by hand. An arrangement records the customer, "
                   "the site, the contract, the schedule and the usual items, "
                   "then raises a reminder activity for its responsible user a "
                   "configurable number of days before the next rental date. "
                   "The user prepares the order with one button: a DRAFT "
                   "gr.rental.order, pre-filled and nothing more. Confirming, "
                   "reserving, inspecting and dispatching stay entirely manual, "
                   "and every existing validation still applies - contract "
                   "approval, asset availability, double-booking, and the "
                   "third-party supplier window and return-buffer rules. A "
                   "template line states a requirement (a 500 kVA generator), "
                   "not a promise of one specific machine; a preferred unit is "
                   "used only when it is genuinely usable on those dates. "
                   "Occurrences are logged as prepared or skipped, which makes "
                   "preparation idempotent and keeps a full audit trail. Part "
                   "of the Generator Rental ERP vertical (gr_* suite) for "
                   "Odoo 19 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_equipment',
                'gr_rental_order', 'gr_rental_items', 'gr_contract',
                'gr_customer_site', 'gr_rental_sublet', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence.xml',
        'data/gr_recurring_rental_cron.xml',
        'views/gr_recurring_rental_views.xml',
        'views/gr_rental_order_recurring_views.xml',
        'views/res_partner_recurring_views.xml',
        'views/gr_recurring_rental_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
