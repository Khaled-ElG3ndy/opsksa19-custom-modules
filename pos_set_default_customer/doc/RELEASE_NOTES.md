# Release notes

## 19.0.1.0.0

Initial release for Odoo 19.

* `Default Customer` on the Point of Sale configuration, surfaced on the
  settings page under `Default Customer in POS Order`.
* The configured customer is preselected on every order the session creates,
  including the one that follows a completed sale.
* The customer is shipped to the session even when it falls outside the
  partners the session would normally preload, and even when another module
  narrows the partner domain.
* Arabic translation, and RTL/LTR both covered by browser tests.
