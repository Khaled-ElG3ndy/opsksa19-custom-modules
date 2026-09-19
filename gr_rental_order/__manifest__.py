# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Rental Orders",
    'summary': "Operational rental execution: reservation, dispatch, install, return, inspection",
    'description': "Operational rental order (gr.rental.order): the execution "
                   "document that ties a contract to a physical generator through "
                   "reservation, dispatch, installation, on-rent, off-hire, return, "
                   "and inspection. Enforces no double-booking, drives asset status, "
                   "captures start/end meter readings, and blocks dispatch when "
                   "maintenance is overdue. Includes checklists and delivery/"
                   "installation/return PDF reports. Part of the Generator Rental "
                   "ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.1',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_contract', 'gr_fleet_base', 'gr_customer_site', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_rental_order_record_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_rental_order_views.xml',
        'views/gr_rental_order_menus.xml',
        'reports/gr_rental_order_report.xml',
        'reports/gr_rental_order_report_templates.xml',
        'wizards/gr_rental_order_return_info_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gr_rental_order/static/src/scss/gr_rental_order_return.scss',
        ],
    },
    'application': False,
    'installable': True,
    'auto_install': False,
}
