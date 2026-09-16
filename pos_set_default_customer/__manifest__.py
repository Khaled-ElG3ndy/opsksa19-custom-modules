# -*- coding: utf-8 -*-
{
    'name': 'POS Default Customer',
    'version': '19.0.1.0.1',
    'category': 'Sales/Point of Sale',
    'summary': 'Set a default customer per Point of Sale, applied to every new order.',
    'description': """
POS Default Customer
====================

Pick a customer on a Point of Sale configuration and every order opened in that
session starts with the customer already set, so the cashier never has to select
it by hand.

* The customer is chosen from **Settings > Point of Sale > Default Customer in
  POS Order**, per Point of Sale.
* The chosen customer is always shipped to the session, even when it falls
  outside the partners the session would normally load.
* Removing the customer from an order still works; only newly created orders get
  the default back.
* Fully translatable and laid out correctly in both LTR and RTL languages
  (Arabic included).
""",
    'author': 'iPredict IT Solutions Pvt. Ltd.',
    'company': 'iPredict IT Solutions Pvt. Ltd.',
    'maintainer': 'iPredict IT Solutions Pvt. Ltd.',
    'website': 'http://ipredictitsolutions.com',
    'depends': ['point_of_sale'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_set_default_customer/static/src/app/services/pos_store.js',
        ],
        'web.assets_tests': [
            'pos_set_default_customer/static/tests/tours/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
