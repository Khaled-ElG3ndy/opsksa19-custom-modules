# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Parts Consumption",
    'summary': "Structured parts consumption on maintenance jobs with real stock "
               "moves, on-hand tracking, and last-purchase-price cost valuation",
    'description': "Parts consumption (gr.parts.consumption.line): records parts "
                   "used on maintenance jobs as real outgoing stock moves that "
                   "decrement on-hand inventory. Part cost is snapshotted at "
                   "consumption from the product Cost (standard_price), which the "
                   "purchase module keeps updated to the last purchase price on "
                   "receipt. Job total parts cost feeds asset cost and "
                   "profitability. Brings full Inventory (stock) and Purchase "
                   "(procurement) into the generator instance. Part of the "
                   "Generator Rental ERP vertical (gr_* suite) for Odoo 18 "
                   "Community.",
    'version': '19.0.1.0.3',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_maintenance',
                'gr_dashboard', 'stock', 'purchase', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_parts_record_rules.xml',
        'data/gr_parts_config.xml',
        'views/gr_parts_consumption_views.xml',
        'views/gr_maintenance_job_parts_views.xml',
        'views/gr_parts_menus.xml',
    ],
    'post_init_hook': 'post_init_configure_parts_category',
    'application': False,
    'installable': True,
    'auto_install': False,
}
