import re

from odoo import http
from odoo.addons.web.controllers.report import ReportController
from odoo.http import content_disposition, request


# The report is also reachable through /report/download, which wraps the same
# call and sets its own attachment header; renaming there would fight it. Only
# the direct route is claimed -- and it carries a language prefix for any
# language that is not the default one, so "/ar/report/pdf/..." is the same
# route and has to match too.
DIRECT_PDF_PATH = re.compile(r"^(/[a-zA-Z]{2}(_[a-zA-Z0-9]+)?)?/report/pdf/")


class JournalEntryReportController(ReportController):
    """Give PDFs opened in a browser tab a meaningful filename."""

    @http.route()
    def report_routes(self, reportname, docids=None, converter=None, **data):
        response = super().report_routes(
            reportname,
            docids=docids,
            converter=converter,
            **data,
        )
        is_direct_journal_pdf = (
            converter == "pdf"
            and reportname == "bi_print_journal_entries.report_journal_entries"
            and docids
            and DIRECT_PDF_PATH.match(request.httprequest.path)
        )
        if not is_direct_journal_pdf:
            return response

        move_ids = [int(record_id) for record_id in docids.split(",") if record_id.isdigit()]
        moves = request.env["account.move"].browse(move_ids).exists()
        if moves:
            filename = f"{moves._get_journal_entry_report_filename()}.pdf"
            response.headers["Content-Disposition"] = content_disposition(
                filename,
                disposition_type="inline",
            )
        return response
