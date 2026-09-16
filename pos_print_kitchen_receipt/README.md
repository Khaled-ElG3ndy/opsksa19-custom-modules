# POS Kitchen Receipt

Copyright 2026 Khaled ElGendy. All rights reserved.

Odoo 19 module for printing a kitchen-only receipt from an active Point of Sale
order before payment. It provides:

- a per-POS **Print Kitchen Receipt** option;
- an optional category-wise receipt;
- product-category exclusions;
- a POS control button, preview screen, and printer/web-print fallback;
- product names (including variant descriptions), customer notes, quantities,
  order identity, and order date on the kitchen receipt.

Install `pos_print_kitchen_receipt` like any other Odoo module, enable it in the
selected Point of Sale settings, then reload the POS session.

## Tests

* `tests/test_pos_print_kitchen_receipt.py` — configuration, settings view and
  the data the Point of Sale is handed.
* `tests/test_pos_print_kitchen_receipt_ui.py` — four browser tours that ring up
  an order and read the kitchen receipt that comes out.
* `static/tests/unit/pos_print_kitchen_receipt.test.js` — the receipt component
  and its category filtering, mounted against a Point of Sale store.

Run them with `--test-enable --test-tags /pos_print_kitchen_receipt`; the
JavaScript unit tests run separately, through
`/web:WebSuite.test_unit_desktop[@pos_print_kitchen_receipt]`.
