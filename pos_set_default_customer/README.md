# POS Default Customer (`pos_set_default_customer`)

Pick a customer on a Point of Sale configuration and every order opened in that
session starts with the customer already set, so the cashier never has to select
it by hand.

Odoo 19 · depends on `point_of_sale` · no other configuration required.

## Using it

*Point of Sale › Configuration › Settings*, select the Point of Sale at the top
of the page, then set **Default Customer** under **Default Customer in POS
Order** and save. Open the register: the order it starts with, and every order
created after a completed sale, already carries that customer.

The cashier can still change the customer or clear it on any individual order —
only newly created orders get the default back.

## How it works

| Piece | What it does |
| --- | --- |
| `pos.config.default_customer_id` | Stores the customer, per Point of Sale. `check_company=True` refuses a customer belonging to another company. |
| `res.config.settings.pos_default_customer_id` | Related field that puts it on the settings page, in its own block after *Product & PoS categories*. |
| `res.partner._load_pos_data_search_read` | Appends the customer to the partners shipped to the session. |
| `pos.config.get_limited_partners_loading` | Also reports it through the core hook, for anything else that reads from there. |
| `PosStore.getDefaultPartnerId` (JS) | Core calls this when it builds a new order; the patch returns the configured customer. |

### Why the partner is added after the search, not through the domain

A Point of Sale preloads only the most-used slice of the address book, so a
customer outside that slice would never reach the browser and the field would
silently resolve to nothing. Widening the domain is not enough either: other
modules AND their own conditions onto it — `pos_customer_restrict`, also
installed here, drops every partner without *Available In POS* — and whether
that condition runs before or after this module's override is just module load
order. Appending the record after the search sidesteps both problems. Reading
still goes through `_load_pos_data_read`, so a customer the session user may not
read is still left out.

Both properties are covered by tests: `test_customer_is_shipped_past_the_partner_cap`
for the cap, and `test_customer_is_shipped_past_a_narrowed_domain` for the
narrowed domain.

### Why `getDefaultPartnerId`

Odoo 19 calls it from `createNewOrder` (to set the customer) and from
`getEmptyOrder` (to decide whether an untouched order can be reused). Patching
that one method covers both, so an order carrying only the default customer is
still recognised as empty instead of piling up new orders.

## Arabic / RTL

Every user-facing string is translatable and `i18n/ar.po` ships the Arabic. The
file is named `ar.po` rather than `ar_001.po` so it also covers `ar_001`,
`ar_SA` and the other Arabic locales, which Odoo resolves through the same base
language.

The module adds no direction-specific styling, so nothing has to be mirrored.
`test_default_customer_survives_a_right_to_left_session` proves it by running
the Point of Sale as an `ar_001` cashier and asserting the session really was
served the RTL stylesheet before checking the customer;
`test_default_customer_in_a_left_to_right_session` is the same tour as the LTR
control.

## Tests

```bash
odoo-bin -d <fresh-db> -i pos_set_default_customer \
         --test-enable --test-tags /pos_set_default_customer --stop-after-init
```

Use a **fresh** database: running with `-u` against a database that has more
modules installed than this module's dependency closure produces spurious
`res_partner` NOT NULL failures that are an artefact of test ordering, not of
the module.

`tests/test_pos_default_customer.py` covers the server (configuration,
multi-company, the settings page, and what a session ships).
`tests/test_pos_default_customer_ui.py` drives a real browser session: a full
sale in LTR, plus the RTL and LTR direction runs. The browser tests need Chrome
and `websocket-client`, and skip themselves when either is missing.
