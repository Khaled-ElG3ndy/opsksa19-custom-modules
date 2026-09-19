# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Return Alerts & Expiry Dashboard",
    'summary': "Working-day-aware alerts for rental returns: due in 3 days, due "
               "today, overdue - with in-system activities, email to managers, "
               "and a dedicated return dashboard",
    'description': "Return alerts (meeting requirement 5). A daily scheduled "
                   "action evaluates every active rental against its planned "
                   "return date, counting only WORKING days (Friday excluded), "
                   "and classifies each into: due within 3 working days, due "
                   "today, or overdue. It raises in-system activities on the "
                   "responsible users, emails the managers when a return is due "
                   "or overdue, and exposes a dedicated dashboard split into the "
                   "three buckets. Also applies to sublet (vendor-side) returns. "
                   "Part of the Generator Rental ERP vertical (gr_* suite) for "
                   "Odoo 18 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_rental_order', 'mail'],
    'data': [
        'data/mail_template.xml',
        'data/ir_cron.xml',
        'views/gr_return_alert_views.xml',
        'views/gr_return_alert_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
