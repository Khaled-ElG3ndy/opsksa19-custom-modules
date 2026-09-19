# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Contracts",
    'summary': "Commercial rental contracts, allocation lines, and amendment workflow",
    'description': "Commercial rental contract (gr.rental.contract): rates, included "
                   "and maximum daily hours, fuel policy, deposits, SLA, approval "
                   "state machine, and a server-side amendment workflow that locks "
                   "commercial fields once approved. Includes contract allocation "
                   "lines and a PDF report. The contract is the pricing source of "
                   "truth for billing. Part of the Generator Rental ERP vertical "
                   "(gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.1',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_customer_site', 'mail', 'account', 'analytic', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_contract_record_rules.xml',
        'data/ir_sequence.xml',
        'data/ir_cron.xml',
        'reports/gr_contract_report.xml',
        'views/gr_rental_contract_views.xml',
        'views/gr_contract_amendment_views.xml',
        'views/gr_contract_menus.xml',
        'reports/gr_contract_report_templates.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
