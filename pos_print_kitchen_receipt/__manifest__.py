# Copyright 2026 Khaled ElGendy
# All rights reserved.

{
    "name": "POS Kitchen Receipt | Customised POS Kitchen Receipt | Print POS Kitchen Receipt",
    "summary": "This module allows Odoo POS users to print a POS kitchen receipt.",
    "version": "19.0.1.0.0",
    "description": """
This module allows Odoo POS users to print a POS kitchen receipt.
""",
    "author": "Khaled ElGendy",
    "maintainer": "Khaled ElGendy",
    "license": "Other proprietary",
    "category": "Point of Sale",
    "depends": [
        "base",
        "point_of_sale",
    ],
    "data": [
        "views/view_pos_config.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_print_kitchen_receipt/static/src/js/**/*.js",
            "pos_print_kitchen_receipt/static/src/xml/**/*.xml",
        ],
        # The sources themselves already reach the unit-test page through
        # web.assets_unit_tests_setup, which includes point_of_sale.assets_prod
        # and therefore point_of_sale._assets_pos. Only the tests go here.
        "web.assets_unit_tests": [
            "pos_print_kitchen_receipt/static/tests/unit/**/*",
        ],
        "web.assets_tests": [
            "pos_print_kitchen_receipt/static/tests/tours/**/*",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "price": 8,
    "currency": "EUR",
    "pre_init_hook": "pre_init_check",
}

