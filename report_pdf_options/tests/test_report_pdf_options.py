from lxml import etree

from odoo.tests.common import TransactionCase


class TestReportPdfOptions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["ir.actions.report"].create({
            "name": "PDF Options Test Report",
            "model": "res.company",
            "report_name": "web.external_layout_standard",
            "report_type": "qweb-pdf",
            "default_print_option": "open",
        })

    def test_default_option_is_available_to_action_service(self):
        self.assertIn(
            "default_print_option", self.report._get_readable_fields()
        )
        action = self.report.report_action(self.env.company)
        self.assertEqual(action["id"], self.report.id)
        self.assertEqual(action["default_print_option"], "open")

    def test_all_print_options_are_accepted(self):
        for option in (False, "print", "download", "open"):
            with self.subTest(option=option):
                self.report.default_print_option = option
                action = self.report.report_action(self.env.company)
                self.assertEqual(action["default_print_option"], option)

    def test_configuration_view_contains_option(self):
        view = self.env.ref("report_pdf_options.act_report_view_inherit")
        arch = etree.tostring(view._get_combined_arch(), encoding="unicode")
        self.assertIn("default_print_option", arch)
