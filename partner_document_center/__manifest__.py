# -*- coding: utf-8 -*-
{
    'name': "Partner Document Center",
    'summary': "One document browser per contact: every attachment reachable "
               "from that partner, from every installed module",
    'description': "Aggregates the attachments of every business record that "
                   "is relationally linked to a contact (sales, invoices, "
                   "payments, purchases, pickings, CRM, projects and any "
                   "custom model registered by a bridge module) into a single "
                   "searchable, filterable document browser on the contact "
                   "form. Pure aggregation layer: it never copies a file, it "
                   "reads standard ir.attachment records and lets Odoo's own "
                   "attachment ACL cascade decide what the user may see. "
                   "Sources are declared, not hardcoded - another module adds "
                   "one by extending partner.document.source.",
    'version': '19.0.1.0.0',
    'category': 'Productivity/Documents',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    # Deliberately minimal. Every business source (sale, purchase, stock,
    # account, crm, project, ...) is resolved at runtime against the registry,
    # so none of them is a dependency. See models/partner_document_source.py.
    'depends': ['base', 'mail', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'security/partner_document_security.xml',
        'data/partner_document_category_data.xml',
        'views/partner_document_category_views.xml',
        'views/res_partner_views.xml',
        'views/partner_document_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'partner_document_center/static/src/document_center/**/*.js',
            'partner_document_center/static/src/document_center/**/*.xml',
            'partner_document_center/static/src/document_center/**/*.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
