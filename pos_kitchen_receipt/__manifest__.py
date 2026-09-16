# Copyright 2026 Khaled ElGendy
# License OPL-1.

{
    "name": "POS Kitchen Receipt",
    "summary": "Adding notes to Kitchen in the POS interface",
    "author": "Khaled ElGendy",
    "maintainer": "Khaled ElGendy",
    "category": "Sales/Point of Sale",
    "version": "19.0.1.0.1",
    "license": "OPL-1",
    "price": 15,
    "currency": "EUR",
    "depends": ["point_of_sale"],
    "data": [
        "views/res_config_settings.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_kitchen_receipt/static/src/js/model.js",
            "pos_kitchen_receipt/static/src/xml/kitchen_receipt.xml",
        ],
        "web.assets_unit_tests": [
            "pos_kitchen_receipt/static/tests/unit/**/*",
        ],
    },
    "application": True,
    "installable": True,
    "auto_install": False,
}
