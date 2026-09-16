from odoo import _, models
from odoo.tools import osutil


class AccountMove(models.Model):
    _inherit = "account.move"

    def _get_journal_entry_report_filename(self):
        """Return a readable, filesystem-safe name for this PDF report."""
        if len(self) == 1:
            entry_number = self.name if self.name and self.name != "/" else str(self.id)
            filename = f"{_('Journal Entry')} - {entry_number}"
        else:
            filename = _("Journal Entries")
        return osutil.clean_filename(filename, replacement="-")

    def action_print_journal_entry(self):
        """Print the current move from the form-view smart button."""
        self.ensure_one()
        lang = self.env.user.lang or self.env.context.get("lang") or "en_US"
        return (
            self.env.ref("bi_print_journal_entries.action_report_journal_entries")
            .with_context(lang=lang)
            .report_action(self.with_context(lang=lang), config=False)
        )
