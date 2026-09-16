# POS Custom Receipt

Customize your Point of Sale receipts effortlessly with the POS Custom Receipt
module, allowing you to tailor the layout, content, and branding to match your
business needs.

Nothing has to be configured. Install the module and both additions appear on
the receipt screen, on the printed ticket, and on every reprint.

## Client Name on POS Receipt

The customer set on the order is printed as a labelled line, directly under
*Served by*:

```
Served by: Mitchell Admin
Client: Billy Fox
```

A customer who belongs to a company is printed as `Client: Deco Addict, Billy
Fox`. An order with no customer prints no client line at all.

The receipt used to carry the customer's name a few lines lower, unlabelled.
That line is removed, so the name is printed once and always with its label;
the address and the VAT number the block also carries are untouched.

## VAT Summary on POS Receipt

A table is printed at the foot of the receipt, one line per VAT rate on the
order:

```
VAT%    VAT     ExVAT   Total
15 %    12.75   85.00   97.75
```

* `VAT%` is the tax's own rate. A tax with no rate to declare - a fixed amount
  per unit, say - shows the rate worked back out of the amounts charged, which
  can only ever agree with the rest of the row.
* `ExVAT` is what the tax was charged on, `Total` is the two added together.
* Rows are **per tax, not per tax group**. The Saudi chart of accounts puts
  15% and the zero-rated taxes in a single *VAT Total Amount* group, so a
  per-group table would print one blended rate for an order carrying both.
* An order with no tax prints no table.

## Languages and reading direction

Every label the module adds is translatable and ships translated into Arabic.
The receipt mirrors with the interface, so an Arabic cashier gets a
right-to-left ticket with Arabic column headers around the same figures:

```
الإجمالي   قبل الضريبة   الضريبة   نسبة الضريبة
97.75      85.00        12.75     15 %
```

The figures themselves stay left to right, and a customer's name is isolated
from the line around it, so a Latin name on an Arabic receipt - or the reverse
- keeps the label, the colon and the name in the right order.

## Tests

    odoo-bin -c <conf> -d <fresh db> -i custom_pos_receipt --without-demo=all \
             --test-enable --test-tags /custom_pos_receipt --stop-after-init

The browser tours need Chrome (`ODOO_BROWSER_BIN`), a writable `HOME` and
`websocket-client`; without them they skip silently and the run still reports
no failures.

## Technical notes

* `point_of_sale.ReceiptHeader` and `point_of_sale.OrderReceipt` are extended,
  never replaced.
* The client line is inserted after the whole contact block rather than after
  the *Served by* line: `l10n_gcc_pos` chains a `t-elif` onto that line, and
  inserting between a `t-if` and its `t-elif` would break it.
* The VAT table goes in the `before-footer` hook the core receipt provides.
* Row figures come from Odoo's own tax aggregation
  (`aggregate_base_lines_tax_details`), keyed per tax instead of per tax group.
