# -*- coding: utf-8 -*-
{
    "name": "OPS Invoice Layout",
    "version": "19.0.2.1.0",
    "summary": "MiKS visual styling for the Saudi customer invoice PDF",
    "description": """
Restyles the customer invoice PDF to the MiKS look by inheriting the standard
Saudi invoice report rather than replacing it, so the ZATCA compliance chain
(l10n_sa + l10n_sa_edi) keeps applying on top of it.

Visual changes only:
  * full 1px grey gridlines and compact padding on the line-item table
  * shaded two-line table header (Arabic above English)
  * compact sans typography set on the report container
  * dd/MM/yyyy dates
  * grand-total bar driven by the company brand colour
""",
    "category": "Accounting/Accounting",
    "author": "OPS",
    "license": "LGPL-3",
    "depends": [
        "account",
        "l10n_gcc_invoice",
        "l10n_sa",
    ],
    "data": [
        "report/invoice_report.xml",
    ],
    "installable": True,
    "application": False,
}
