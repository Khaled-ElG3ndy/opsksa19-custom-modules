# -*- coding: utf-8 -*-
{
    # App information
    'name': 'BOM Recipe',
    'category': '',
    'summary': 'Basic module for BOM Recipe',
    'description': 'Basic module for BOM Recipe',
    'version': '17.0.0.2',
    'author': "MP Technolabs",
    'license': 'LGPL-3',
    'company': 'TechUltra Solution',
    'website': "https://www.mptechnolabs.com",

    # Dependencies
    'depends': ['mrp'],

    # Data
    'data': [
        'views/mrp_views.xml',
    ],

    # Technical
    'installable': True,
    'auto_install': False,
    'application': False,
}
