# Copyright 2026 Khaled ElGendy
# License OPL-1.

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open


@tagged("post_install", "-at_install")
class TestPosKitchenReceipt(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env["pos.config"].create({"name": "Kitchen Receipt Test"})

    def test_option_is_enabled_by_default(self):
        self.assertTrue(self.config.print_kitchen_notes_receipt)

    def test_settings_option_updates_selected_pos(self):
        settings = self.env["res.config.settings"].create({
            "pos_config_id": self.config.id,
        })

        settings.print_kitchen_notes_receipt = False

        self.assertFalse(self.config.print_kitchen_notes_receipt)

    def test_option_is_loaded_into_the_pos(self):
        records = self.env["pos.config"]._load_pos_data_search_read({}, self.config)

        self.assertEqual(len(records), 1)
        self.assertIn("print_kitchen_notes_receipt", records[0])
        self.assertTrue(records[0]["print_kitchen_notes_receipt"])

    def test_settings_view_is_valid_and_contains_the_option(self):
        view = self.env.ref(
            "pos_kitchen_receipt.pos_kitchen_receipt_res_config_settings_view_form"
        )
        combined_arch = self.env["res.config.settings"].get_view(view_id=view.id)["arch"]
        document = etree.fromstring(combined_arch.encode())

        self.assertTrue(
            document.xpath("//field[@name='print_kitchen_notes_receipt']")
        )

    def test_receipt_template_keeps_the_note_and_font_customizations(self):
        with file_open(
            "pos_kitchen_receipt/static/src/xml/kitchen_receipt.xml", mode="rb"
        ) as template_file:
            document = etree.parse(template_file)

        note_block = document.xpath("//div[contains(@class, 'pos-order-notes')]")
        self.assertEqual(len(note_block), 1)
        # Asserted on the class and on what the condition mentions rather than
        # on the literal t-if, so that tightening the condition -- as it was
        # tightened to stop the note printing twice -- does not read as a
        # regression here.
        condition = note_block[0].get("t-if")
        self.assertIn("data.order_note", condition)
        self.assertIn("data.general_customer_note", condition)
        self.assertTrue(document.xpath("//t[@t-esc='data.order_note']"))
        self.assertTrue(
            document.xpath(
                "//attribute[@name='style' and "
                "contains(@add, 'font-size: 25px')]"
            )
        )
