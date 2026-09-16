# POS Kitchen Receipt

Copyright 2026 Khaled ElGendy. All rights reserved.

Odoo 19 port of POS Kitchen Receipt. When **Kitchen Note on Receipt** is enabled
for a Point of Sale, its whole-order note is printed on every kitchen/preparation
change receipt.

The port keeps the original model field and visible behavior while adapting the
frontend patch to Odoo 19's `PosStore` preparation-printing service.
