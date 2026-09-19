# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Hour Logs",
    'summary': "Hour-meter logs with regular/overtime/violation calculation, "
               "violation approval gate, and asset meter/maintenance sync",
    'description': "Hour logs (gr.hour.log): per-rental meter readings with a "
                   "flexible reading date. Computes used/regular/overtime/"
                   "violation hours by scaling the contract's per-day included "
                   "and max allowances across the days each reading covers "
                   "(derived from reading dates, not entered by hand). Violations "
                   "force a manager approval gate and raise an alert to Operations "
                   "and Sales. On approval the asset meter advances (respecting the "
                   "no-rollback rule) and the asset auto-transitions to "
                   "Maintenance Due when it crosses its PM threshold. Approved "
                   "logs lock; changes go through an audited correction. Feeds "
                   "billing. Part of the Generator Rental ERP vertical (gr_* suite) "
                   "for Odoo 18 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_contract',
                'gr_rental_order', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_hour_log_record_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_hour_log_views.xml',
        'views/gr_hour_log_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
