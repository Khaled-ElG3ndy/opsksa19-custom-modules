# -*- coding: utf-8 -*-
{
    'name': 'POS Custom Receipt',
    'version': '19.0.1.0.1',
    'category': 'Sales/Point of Sale',
    'summary': 'Customize the Point of Sale receipt: client name and a VAT summary table.',
    'description': """
POS Custom Receipt
==================

Customize your Point of Sale receipts effortlessly with the POS Custom Receipt
module, allowing you to tailor the layout, content, and branding to match your
business needs.

Client Name on POS Receipt
--------------------------
The customer set on the order is printed as a labelled **Client:** line, right
under *Served by*, on the receipt screen, on the printed ticket and on every
reprint. The unlabelled name the receipt used to carry is removed, so the name
is shown once and always with its label.

VAT Summary on POS Receipt
--------------------------
A **VAT% / VAT / ExVAT / Total** table is printed at the foot of the receipt,
one line per VAT rate on the order, so the customer can read what was taxed and
at which rate.

Key Features
------------
* Fully customizable Point of Sale (POS) receipts.
* Easy to use with no additional configuration required.
* Compatible across all major browsers.
* Fully translatable, and laid out correctly in both LTR and RTL languages
  (Arabic included).
""",
    'author': 'Kanak Infosystems LLP.',
    'company': 'Kanak Infosystems LLP.',
    'maintainer': 'Kanak Infosystems LLP.',
    'website': 'https://www.kanakinfosystems.com',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'custom_pos_receipt/static/src/app/screens/receipt_screen/receipt/receipt_header.js',
            'custom_pos_receipt/static/src/app/screens/receipt_screen/receipt/order_receipt.js',
            'custom_pos_receipt/static/src/app/screens/receipt_screen/receipt/receipt_header.xml',
            'custom_pos_receipt/static/src/app/screens/receipt_screen/receipt/order_receipt.xml',
            'custom_pos_receipt/static/src/scss/custom_pos_receipt.scss',
        ],
        'web.assets_tests': [
            'custom_pos_receipt/static/tests/tours/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
