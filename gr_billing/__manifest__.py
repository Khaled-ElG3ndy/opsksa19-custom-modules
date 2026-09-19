# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Billing",
    'summary': "Generate draft, itemized, ZATCA-aware customer invoices from "
               "approved hour logs (per rental order, per period)",
    'description': "Billing (gr.billing.run): generates draft account.move "
                   "customer invoices from approved hour logs, grouped per "
                   "rental order per date range (monthly or on-demand). Lines are "
                   "fully itemized in SAR: base rental, overtime, violation, "
                   "standby, fuel, mobilization, demobilization, and deposit, "
                   "each with 15% KSA VAT via a proper account.tax. Each approved "
                   "log is billed exactly once (invoice_id link + billed flag); "
                   "generation is idempotent and reversible. Invoices are draft "
                   "only - finance reviews and posts. Part of the Generator "
                   "Rental ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.9',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_contract',
                'gr_rental_order', 'gr_rental_items', 'gr_hour_log',
                'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_billing_record_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_hour_log_billing_views.xml',
        'views/account_move_billing_views.xml',
        'views/gr_rental_order_billing_views.xml',
        'views/gr_billing_run_views.xml',
        'views/gr_billing_menus.xml',
    ],
    'post_init_hook': 'post_init_create_tax',
    'application': False,
    'installable': True,
    'auto_install': False,
}
