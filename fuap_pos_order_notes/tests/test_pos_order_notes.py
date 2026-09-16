# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosOrderNotes(TestPoSCommon):
    """Server-side behavior of POS Order Notes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.product = cls.create_product(
            "Order Note Product",
            cls.categ_basic,
            10.0,
            5.0,
        )
        cls.tags = cls.env["pos.order.note"].create([
            {"name": "1-year warranty", "sequence": 10},
            {"name": "Gluten free", "sequence": 20},
            {"name": "Order assembled", "sequence": 30},
        ])
        cls.unselected_tag = cls.env["pos.order.note"].create({
            "name": "Not selected",
        })
        cls.config.order_note_ids = cls.tags

        cls.env["res.lang"]._activate_lang("ar_001")
        cls.env.ref("base.module_fuap_pos_order_notes")._update_translations(["ar_001"])
        cls.tags[2].with_context(lang="ar_001").name = "تم تجهيز الطلب"

    def _sync_paid_order(self, note, *, to_invoice=False):
        self.open_new_session()
        order_data = self.create_ui_order_data(
            [(self.product, 1)],
            pos_order_ui_args={"order_note": note},
            customer=self.customer if to_invoice else False,
            is_invoiced=to_invoice,
        )
        result = self.env["pos.order"].sync_from_ui([order_data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])

    # Configuration and tags -------------------------------------------------

    def test_receipt_option_defaults_to_enabled(self):
        fresh_config = self.env["pos.config"].create({
            "name": "Order Notes Default Test",
        })
        self.assertTrue(fresh_config.order_note_on_receipt)

    def test_settings_write_through_to_pos_config(self):
        settings = self.env["res.config.settings"].create({
            "pos_config_id": self.config.id,
            "pos_order_note_on_receipt": False,
            "pos_order_note_ids": [(6, 0, self.tags[:2].ids)],
        })
        settings.execute()

        self.assertFalse(self.config.order_note_on_receipt)
        self.assertEqual(self.config.order_note_ids, self.tags[:2])

    def test_only_configured_tags_are_loaded_in_sequence(self):
        records = self.env["pos.order.note"]._load_pos_data_search_read({}, self.config)

        self.assertEqual(
            [record["id"] for record in records],
            self.tags.ids,
        )
        self.assertNotIn(self.unselected_tag.id, [record["id"] for record in records])

    def test_order_note_model_is_part_of_session_payload(self):
        self.assertIn("pos.order.note", self.env["pos.session"]._load_pos_data_models(self.config))

    def test_tag_names_support_language_specific_values(self):
        records = self.env["pos.order.note"].with_context(
            lang="ar_001",
        )._load_pos_data_search_read({}, self.config)
        translated = next(record for record in records if record["id"] == self.tags[2].id)

        self.assertEqual(translated["name"], "تم تجهيز الطلب")
        self.assertEqual(
            self.env["pos.order"].with_context(lang="ar_001").fields_get(
                ["order_note"],
            )["order_note"]["string"],
            "ملاحظة الطلب",
        )

    def test_cashier_can_read_but_cannot_manage_tags(self):
        cashier = new_test_user(
            self.env,
            login="order_note_cashier",
            groups="base.group_user,point_of_sale.group_pos_user",
        )

        self.assertEqual(self.tags[0].with_user(cashier).name, "1-year warranty")
        with self.assertRaises(AccessError):
            self.env["pos.order.note"].with_user(cashier).create({"name": "Forbidden"})

    # Order synchronization and downstream documents ------------------------

    def test_order_note_round_trips_through_pos_sync_and_reload(self):
        note = "Handle carefully, Gluten free"
        order = self._sync_paid_order(note)

        self.assertEqual(order.order_note, note)
        loaded = order.read_pos_data([], self.config)["pos.order"]
        self.assertEqual(loaded[0]["order_note"], note)

    def test_order_note_is_copied_safely_to_delivery(self):
        note = "Handle carefully\n<script>alert(1)</script> العربية"
        order = self._sync_paid_order(note)

        self.assertTrue(order.picking_ids)
        picking_note = str(order.picking_ids[0].note)
        self.assertIn("Handle carefully", picking_note)
        self.assertIn("العربية", picking_note)
        self.assertIn("&lt;script&gt;", picking_note)
        self.assertNotIn("<script>", picking_note)
        self.assertIn("<br>", picking_note)

    def test_order_note_is_copied_safely_to_invoice(self):
        note = "Invoice note\n<b>not markup</b>"
        order = self._sync_paid_order(note, to_invoice=True)

        self.assertTrue(order.account_move)
        narration = str(order.account_move.narration)
        self.assertIn("Invoice note", narration)
        self.assertIn("&lt;b&gt;not markup&lt;/b&gt;", narration)
        self.assertNotIn("<b>not markup</b>", narration)
        self.assertFalse(
            order.account_move.invoice_line_ids.filtered(
                lambda line: line.display_type == "line_note" and line.name == note
            ),
            "the independent order note must not be duplicated as an invoice line",
        )

    def test_backend_edit_updates_existing_delivery_and_invoice(self):
        order = self._sync_paid_order("Original", to_invoice=True)

        order.order_note = "Updated from backend العربية"

        self.assertIn("Updated from backend العربية", str(order.picking_ids[0].note))
        self.assertIn("Updated from backend العربية", str(order.account_move.narration))

    def test_clearing_backend_note_clears_existing_documents(self):
        order = self._sync_paid_order("Temporary", to_invoice=True)

        order.order_note = False

        self.assertFalse(order.picking_ids[0].note)
        self.assertFalse(order.account_move.narration)
