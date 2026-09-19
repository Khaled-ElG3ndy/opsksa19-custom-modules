# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Maintenance Contracts",
    'summary': "Recurring paid maintenance contracts on customer-owned "
               "generators: scheduled visits, consumable cadence, split-payment "
               "billing, and emergency T&M",
    'description': "Maintenance contracts (gr.maintenance.contract) - ABSAL's "
                   "third business model. Recurring paid service on CUSTOMER-OWNED "
                   "generators (the units M11 keeps out of the rental pool). "
                   "Models ABSAL's real Perkins contract: periodic visits "
                   "(e.g. monthly for a year) auto-generating M7 maintenance jobs "
                   "tagged as COVERED; a consumable cadence (oil + filters every N "
                   "months, batteries once) surfaced as due; a split-payment "
                   "billing schedule (e.g. 50% every 6 months) generating draft "
                   "invoices; and out-of-scope EMERGENCY / T&M visits billed "
                   "separately at a per-visit rate. Covered vs T&M is explicit on "
                   "every generated job. Part of the Generator Rental ERP vertical "
                   "(gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_equipment',
                'gr_maintenance', 'gr_billing', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_maintenance_contract_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_maintenance_contract_views.xml',
        'views/gr_maintenance_job_contract_views.xml',
        'views/gr_maintenance_contract_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
