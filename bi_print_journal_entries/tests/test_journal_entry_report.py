from io import BytesIO

from lxml import etree

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingHttpCommon
from odoo.tests import tagged
from odoo.tools.pdf import OdooPdfFileReader


@tagged("post_install", "-at_install")
class TestJournalEntryReport(AccountTestInvoicingHttpCommon):
    """The report, in both languages it is meant to be printed in.

    An HttpCase rather than a plain TransactionCase because the two PDF tests
    below really do run wkhtmltopdf, which fetches the report stylesheets back
    out of this same Odoo over HTTP. On a database whose asset bundles have not
    been generated yet that fetch has to write them, and from an ordinary test
    transaction the two sides deadlock: wkhtmltopdf waits for the stylesheet and
    the request waits for the test's transaction. An HttpCase shares its cursor
    with the request threads, so the fetch completes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Arabic is asserted on throughout, so it is activated rather than
        # assumed: a database installed without it would otherwise fail here
        # with "Invalid language code" instead of testing anything. Activating a
        # language does not retranslate modules installed before it, so this
        # module's own catalogue is loaded too.
        cls.env["res.lang"]._activate_lang("ar_001")
        cls.env["ir.module.module"].search(
            [("name", "=", "bi_print_journal_entries")]
        )._update_translations(["ar_001"])

        # The HTTP half of these tests downloads reports as `admin`, while the
        # entries below belong to the throwaway company the accounting test
        # harness sets up. Without letting admin into that company the download
        # comes back 403 and says nothing about the controller under test.
        cls.env.ref("base.user_admin").write({
            "company_ids": [(4, cls.env.company.id)],
            "company_id": cls.env.company.id,
        })

        cls.report_xmlid = "bi_print_journal_entries.action_report_journal_entries"
        cls.partner = cls.env["res.partner"].create({"name": "Journal Report Partner"})
        cls.moves = cls.env["account.move"]
        for index, amount in enumerate((125.50, 275.75), start=1):
            move = cls.env["account.move"].create(
                {
                    "move_type": "entry",
                    "date": f"2026-08-{index:02d}",
                    "journal_id": cls.company_data["default_journal_misc"].id,
                    "ref": f"REPORT-REF-{index}",
                    "line_ids": [
                        Command.create(
                            {
                                "name": f"Debit line {index}",
                                "partner_id": cls.partner.id,
                                "account_id": cls.company_data["default_account_expense"].id,
                                "debit": amount,
                            }
                        ),
                        Command.create(
                            {
                                "name": f"Credit line {index}",
                                "partner_id": cls.partner.id,
                                "account_id": cls.company_data["default_account_revenue"].id,
                                "credit": amount,
                            }
                        ),
                    ],
                }
            )
            move.action_post()
            cls.moves |= move

    def _render_html(self, lang):
        self.env.user.lang = lang
        html, report_type = (
            self.env["ir.actions.report"]
            .with_context(lang="en_US" if lang == "ar_001" else "ar_001")
            ._render_qweb_html(self.report_xmlid, self.moves.ids)
        )
        self.assertEqual(report_type, "html")
        return html.decode()

    def test_report_action_is_bound_to_form_and_list(self):
        action = self.env.ref(self.report_xmlid)
        self.assertEqual(action.model, "account.move")
        self.assertEqual(action.report_type, "qweb-pdf")
        self.assertEqual(action.binding_type, "report")
        self.assertEqual(action.binding_model_id.model, "account.move")
        self.assertEqual(set(action.binding_view_types.split(",")), {"form", "list"})
        self.assertEqual(
            action.print_report_name,
            "object._get_journal_entry_report_filename()",
        )
        self.assertEqual(action.with_context(lang="en_US").name, "Print Journal Entries")
        self.assertEqual(action.with_context(lang="ar_001").name, "طباعة القيود")

    def test_pdf_filename_is_readable_and_localized(self):
        move = self.moves[:1]
        safe_number = move.name.replace("/", "-")
        self.assertEqual(
            move.with_context(lang="en_US")._get_journal_entry_report_filename(),
            f"Journal Entry - {safe_number}",
        )
        self.assertEqual(
            move.with_context(lang="ar_001")._get_journal_entry_report_filename(),
            f"قيد اليومية - {safe_number}",
        )
        self.assertEqual(
            self.moves.with_context(lang="en_US")._get_journal_entry_report_filename(),
            "Journal Entries",
        )
        self.assertEqual(
            self.moves.with_context(lang="ar_001")._get_journal_entry_report_filename(),
            "قيود اليومية",
        )

    def test_form_smart_button_prints_the_current_entry(self):
        view = self.env.ref(
            "bi_print_journal_entries.view_move_form_inherit_print_journal_entries"
        )
        self.assertIn("action_print_journal_entry", view.arch_db)
        self.assertIn("fa-print", view.arch_db)

        base_view = self.env.ref("account.view_move_form")
        for lang, expected in (("en_US", "Print Entry"), ("ar_001", "طباعة القيد")):
            view_data = self.env["account.move"].with_context(lang=lang).get_view(
                view_id=base_view.id,
                view_type="form",
            )
            arch = etree.fromstring(view_data["arch"].encode())
            buttons = arch.xpath(
                "//div[@name='button_box']"
                "//button[@name='action_print_journal_entry']"
            )
            self.assertEqual(len(buttons), 1)
            self.assertEqual(buttons[0].get("icon"), "fa-print")
            self.assertIn(expected, "".join(buttons[0].itertext()))

        move = self.moves[:1]
        self.env.user.lang = "ar_001"
        result = move.with_context(lang="en_US").action_print_journal_entry()
        self.assertEqual(result["type"], "ir.actions.report")
        self.assertEqual(
            result["report_name"],
            "bi_print_journal_entries.report_journal_entries",
        )
        self.assertEqual(result["context"]["active_ids"], move.ids)
        self.assertEqual(result["context"]["lang"], "ar_001")

    def test_english_report_content_and_direction(self):
        html = self._render_html("en_US")
        self.assertEqual(html.count('class="page bi_journal_entry_report bi_ltr"'), 2)
        self.assertIn('dir="ltr"', html)
        self.assertEqual(etree.HTML(html).xpath("//body/@dir"), ["ltr"])
        for text in (
            "Journal Entry",
            "Entry Number",
            "Date",
            "Journal",
            "Status",
            "Reference",
            "Account",
            "Label",
            "Partner",
            "Debit",
            "Credit",
            "Total",
            "REPORT-REF-1",
            "REPORT-REF-2",
        ):
            self.assertIn(text, html)

    def test_arabic_report_content_and_direction(self):
        html = self._render_html("ar_001")
        self.assertEqual(html.count('class="page bi_journal_entry_report bi_rtl"'), 2)
        self.assertIn('dir="rtl"', html)
        self.assertEqual(etree.HTML(html).xpath("//body/@dir"), ["rtl"])
        for text in (
            "قيد اليومية",
            "رقم القيد",
            "التاريخ",
            "اليومية",
            "الحالة",
            "المرجع",
            "الحساب",
            "البيان",
            "الشريك",
            "مدين",
            "دائن",
            "الإجمالي",
        ):
            self.assertIn(text, html)

    def test_multiple_entries_generate_one_pdf_page_each(self):
        self.env.user.lang = "en_US"
        pdf_content, report_type = (
            self.env["ir.actions.report"]
            .with_context(lang="en_US", force_report_rendering=True)
            ._render_qweb_pdf(self.report_xmlid, res_ids=self.moves.ids)
        )
        self.assertEqual(report_type, "pdf")
        self.assertTrue(pdf_content.startswith(b"%PDF"))
        reader = OdooPdfFileReader(BytesIO(pdf_content), strict=False)
        self.assertEqual(reader.getNumPages(), 2)

    def test_single_entry_generates_one_pdf_page(self):
        self.env.user.lang = "ar_001"
        pdf_content, report_type = (
            self.env["ir.actions.report"]
            .with_context(lang="ar_001", force_report_rendering=True)
            ._render_qweb_pdf(self.report_xmlid, res_ids=self.moves[:1].ids)
        )
        self.assertEqual(report_type, "pdf")
        self.assertTrue(pdf_content.startswith(b"%PDF"))
        reader = OdooPdfFileReader(BytesIO(pdf_content), strict=False)
        self.assertEqual(reader.getNumPages(), 1)

    # -- the controller that names the file a browser downloads ------------

    def _content_disposition(self, url):
        """Fetch ``url`` as the logged-in user and return its Content-Disposition.

        The body is not asserted on: ``_pre_render_qweb_pdf`` deliberately falls
        back to HTML while tests run, so what comes back here is the rendered
        report rather than a PDF. The controller under test sets the header from
        the route and the ids, not from the body, so the header is still the
        real thing -- and the two tests above cover the PDF itself.
        """
        self.authenticate("admin", "admin")
        response = self.url_open(url, timeout=120)
        self.assertEqual(response.status_code, 200)
        return response.headers.get("Content-Disposition", "")

    def test_a_downloaded_entry_is_named_after_the_entry(self):
        """The filename is the point of the controller override.

        Odoo names a directly-opened report PDF after the report itself, so
        every journal entry would arrive as the same opaque name. The override
        replaces it, and nothing else asserts that it still fires.
        """
        move = self.moves[:1]
        disposition = self._content_disposition(
            f"/report/pdf/bi_print_journal_entries.report_journal_entries/{move.id}"
        )

        self.assertIn("inline", disposition)
        self.assertIn(move.name.replace("/", "-"), disposition)
        self.assertIn("Journal%20Entry", disposition.replace("+", "%20"))

    def test_several_entries_downloaded_together_get_the_plural_name(self):
        disposition = self._content_disposition(
            "/report/pdf/bi_print_journal_entries.report_journal_entries/"
            + ",".join(str(move_id) for move_id in self.moves.ids)
        )

        self.assertIn("Journal%20Entries", disposition.replace("+", "%20"))

    def test_the_override_leaves_every_other_report_alone(self):
        """A controller that renamed unrelated downloads would be a regression.

        The override sits on the route every report PDF goes through, so the
        guard that keeps it to this one report is worth an assertion of its own.
        """
        invoice = self._create_invoice_one_line(price_unit=100.0, post=True)
        disposition = self._content_disposition(
            f"/report/pdf/account.account_invoices/{invoice.id}"
        )

        self.assertNotIn("Journal", disposition)

    def test_a_download_asked_for_in_arabic_is_named_in_arabic(self):
        """The filename follows the language the request is made in."""
        self.env.ref("base.user_admin").lang = "ar_001"
        move = self.moves[:1]
        try:
            disposition = self._content_disposition(
                f"/report/pdf/bi_print_journal_entries.report_journal_entries/{move.id}"
            )
        finally:
            self.env.ref("base.user_admin").lang = "en_US"

        # "قيد اليومية", percent-encoded the way Content-Disposition carries it.
        self.assertIn("%D9%82%D9%8A%D8%AF", disposition)
