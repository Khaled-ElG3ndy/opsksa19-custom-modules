# -*- coding: utf-8 -*-
{
    'name': 'POS Timeslot',
    'version': '17.0.0.0.3',
    'category': '',
    'author': 'MP Technolabs',
    'summary': 'POS Timeslot',
    'description': """
         POS Timeslot
    """,
    'website': "www.mptechnolabs.com",
    'depends': ['point_of_sale',],
    'data': [
        'security/ir.model.access.csv',

        'views/timeslot_views.xml',
        'views/pos_order_views.xml',
    ],
    'application': True,
    'license': 'LGPL-3',
}
