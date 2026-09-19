# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Customer Approval (Signature & OTP)",
    'summary': "Customer approves documents in person by signature, or remotely "
               "with a one-time code (OTP) sent to mobile or email",
    'description': "Customer approval (meeting requirement 6). Any document that "
                   "needs the customer's agreement can be approved two ways: the "
                   "customer signs on screen when present, or - when they are not "
                   "present - the system issues a one-time code (OTP) to their "
                   "mobile or email; entering the correct code marks the document "
                   "Approved. The approval (who, when, by which method) is stored "
                   "permanently on the document.\n\n"
                   "Applied to the four moments the client named:\n"
                   "  1. the rental order / contract,\n"
                   "  2. delivery of the asset to the customer,\n"
                   "  3. every service visit report,\n"
                   "  4. the return record.\n\n"
                   "Implemented as a reusable approval mixin so all documents "
                   "behave identically. The OTP SENDER is channel-agnostic: email "
                   "works out of the box, and WhatsApp/SMS can be plugged in later "
                   "without touching this logic. Part of the Generator Rental ERP "
                   "vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.2',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_rental_order', 'gr_rental_items',
                'gr_rental_inspection', 'gr_field_worksheet', 'mail'],
    'external_dependencies': {'python': ['PIL', 'reportlab', 'pypdf']},
    'data': [
        'security/ir.model.access.csv',
        'reports/gr_approval_reports.xml',
        'reports/gr_approval_report_templates.xml',
        'reports/gr_unified_legacy_reports.xml',
        'data/mail_template.xml',
        'views/gr_approval_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
