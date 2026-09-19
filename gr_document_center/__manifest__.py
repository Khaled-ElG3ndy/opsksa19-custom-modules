# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Document Center Sources",
    'summary': "Teaches the partner Document Center about the gr_* business "
               "records: rental orders, contracts, sites, maintenance, "
               "billing runs and sublet agreements",
    'description': "Bridge module. It adds no model, no view and no security "
                   "rule: it only extends partner.document.source with the "
                   "gr_* models that hold a real relation to a contact, so "
                   "their attachments show up in that contact's Document "
                   "Center alongside the standard Odoo ones. Every source is "
                   "resolved at runtime, so this module stays installable "
                   "whatever subset of the gr_* suite is present.",
    'version': '19.0.1.0.1',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['partner_document_center', 'gr_security_base'],
    'data': [],
    'installable': True,
    'application': False,
    # Meaningless without the Document Center, and desirable the moment both
    # the Document Center and the gr_* suite are present.
    'auto_install': True,
}
