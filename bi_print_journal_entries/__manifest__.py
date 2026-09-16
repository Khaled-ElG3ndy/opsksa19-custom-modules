{
    "name": "Print Journal Entries Report in Odoo",
    "version": "19.0.1.4.2",
    "category": "Accounting/Accounting",
    "summary": "Print one or multiple journal entries as a PDF report",
    "description": """Adds a bilingual PDF report to account moves.

The report is available from the Print menu in form and list views, prints
every selected entry on its own page, and automatically follows the current
user's LTR or RTL language.
""",
    "author": "OPS KSA",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "report/report_journal_entries.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
