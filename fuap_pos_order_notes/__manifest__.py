# -*- coding: utf-8 -*-
{
    "name": "POS Order Notes",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Define order notes from the Point of Sale interface and backend",
    "description": """
POS Order Notes
===============

* Add a free-text note to a complete Point of Sale order.
* Insert preconfigured order-note tags from the Point of Sale popup.
* Optionally print the note on original and reprinted POS receipts.
* Copy the note to the delivery note and customer invoice.
* Work in English and Arabic, including LTR and RTL interfaces.
""",
    "author": "Custom Development",
    "website": "",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/pos_order_note_views.xml",
        "views/res_config_settings_views.xml",
        "views/pos_order_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "fuap_pos_order_notes/static/src/app/models/pos_order.js",
            "fuap_pos_order_notes/static/src/app/components/order_note_popup/order_note_popup.js",
            "fuap_pos_order_notes/static/src/app/components/order_note_popup/order_note_popup.xml",
            "fuap_pos_order_notes/static/src/app/components/order_note_button/order_note_button.js",
            "fuap_pos_order_notes/static/src/app/components/order_note_button/order_note_button.xml",
            "fuap_pos_order_notes/static/src/app/receipt/order_receipt.xml",
            "fuap_pos_order_notes/static/src/scss/order_note.scss",
        ],
        "web.assets_tests": [
            "fuap_pos_order_notes/static/tests/tours/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
