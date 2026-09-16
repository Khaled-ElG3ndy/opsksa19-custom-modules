# Copyright 2026 Khaled ElGendy
# All rights reserved.

from lxml import etree

from odoo.modules.module import get_manifest
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open


@tagged("post_install", "-at_install")
class TestPosPrintKitchenReceipt(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env["product.category"].create({"name": "Kitchen Excluded"})
        cls.config = cls.env["pos.config"].create(
            {
                "name": "Kitchen Receipt Test",
                "print_kitchen_categories_exclude_ids": [(6, 0, cls.category.ids)],
            }
        )

    def test_configuration_defaults_and_field_contract(self):
        self.assertFalse(self.config.print_kitchen_receipt)
        self.assertFalse(self.config.print_kitchen_receipt_categ)
        field = self.config._fields["print_kitchen_categories_exclude_ids"]
        self.assertEqual(field.comodel_name, "product.category")
        self.assertEqual(field.relation, "kitchen_print_category_rel")

    def test_settings_update_the_selected_pos(self):
        settings = self.env["res.config.settings"].create(
            {
                "pos_config_id": self.config.id,
                "print_kitchen_receipt": True,
                "print_kitchen_receipt_categ": True,
            }
        )
        self.assertTrue(settings.print_kitchen_receipt)
        self.assertTrue(self.config.print_kitchen_receipt)
        self.assertTrue(self.config.print_kitchen_receipt_categ)
        self.assertEqual(settings.print_kitchen_categories_exclude_ids, self.category)

    def test_configuration_is_loaded_into_the_pos(self):
        records = self.env["pos.config"]._load_pos_data_search_read({}, self.config)
        self.assertEqual(len(records), 1)
        self.assertIn("print_kitchen_receipt", records[0])
        self.assertIn("print_kitchen_receipt_categ", records[0])
        self.assertIn("print_kitchen_categories_exclude_ids", records[0])
        self.assertEqual(records[0]["print_kitchen_categories_exclude_ids"], self.category.ids)

    def test_settings_view_is_valid_and_contains_all_options(self):
        view = self.env.ref(
            "pos_print_kitchen_receipt.res_config_settings_view_form_inherit_kitchen_receipt"
        )
        combined_arch = self.env["res.config.settings"].get_view(view_id=view.id)["arch"]
        document = etree.fromstring(combined_arch.encode())
        for field_name in (
            "print_kitchen_receipt",
            "print_kitchen_receipt_categ",
            "print_kitchen_categories_exclude_ids",
        ):
            self.assertTrue(document.xpath(f"//field[@name='{field_name}']"), field_name)

    def test_manifest_targets_odoo_19_and_has_requested_ownership(self):
        manifest = get_manifest("pos_print_kitchen_receipt")
        self.assertEqual(manifest["version"], "19.0.1.0.0")
        self.assertEqual(manifest["author"], "Khaled ElGendy")
        self.assertEqual(manifest["maintainer"], "Khaled ElGendy")
        self.assertEqual(manifest["license"], "Other proprietary")
        self.assertIn("point_of_sale._assets_pos", manifest["assets"])

    def test_frontend_templates_cover_button_screen_receipt_and_filtering(self):
        template_paths = (
            "pos_print_kitchen_receipt/static/src/xml/KitchenReceipt.xml",
            "pos_print_kitchen_receipt/static/src/xml/PrintkitchenReceiptButton.xml",
            "pos_print_kitchen_receipt/static/src/xml/PrintkitchenReceiptScreen.xml",
        )
        documents = []
        for template_path in template_paths:
            with file_open(template_path, mode="rb") as template_file:
                documents.append(etree.parse(template_file))

        receipt, button, screen = documents
        self.assertTrue(receipt.xpath("//t[@t-name='pos_print_kitchen_receipt.KitchenReceipt']"))
        self.assertTrue(receipt.xpath("//*[@t-foreach='orderCategories']"))
        self.assertTrue(receipt.xpath("//*[@t-esc='lineCustomerNote(line)']"))
        self.assertTrue(button.xpath("//PrintKitchenReceiptButton"))
        self.assertTrue(screen.xpath("//KitchenReceipt[@order='currentOrder']"))

