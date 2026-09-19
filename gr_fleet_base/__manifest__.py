# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Fleet Base",
    'summary': "Generator asset master and controlled meter-correction wizard",
    'description': "Generator asset master (gr.generator.asset) with status state "
                   "machine, hour-meter tracking, PM thresholds, and an audit-safe "
                   "meter-correction wizard. Standalone in M1; stock/serial linkage "
                   "is added at the parts/inventory milestone. Part of the Generator "
                   "Rental ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.1.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'mail', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_fleet_record_rules.xml',
        'data/ir_sequence.xml',
        'views/gr_generator_asset_views.xml',
        'wizards/gr_meter_correction_wizard_views.xml',
        'views/gr_fleet_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
