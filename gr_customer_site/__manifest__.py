# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Customer Sites",
    'summary': "Customer project/site master where generators are installed",
    'description': "Customer site master (gr.customer.site): the physical "
                   "project locations where generators are deployed. Holds the "
                   "customer link, location/GPS, site type, load requirements, "
                   "access and safety notes, and PO policy. Standalone records "
                   "linked to res.partner (not child contacts). Part of the "
                   "Generator Rental ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'mail', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_site_record_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_customer_site_views.xml',
        'views/gr_customer_site_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
