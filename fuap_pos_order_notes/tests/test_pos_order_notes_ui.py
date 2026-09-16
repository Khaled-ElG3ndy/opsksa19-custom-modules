# -*- coding: utf-8 -*-
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestPosOrderNotesUi(TestPointOfSaleHttpCommon):
    """Real-browser checks for popup, receipts, translations, LTR and RTL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order_note_tags = cls.env["pos.order.note"].create([
            {"name": "1-year warranty", "sequence": 10},
            {"name": "Gluten free", "sequence": 20},
            {"name": "Order assembled", "sequence": 30},
        ])
        cls.main_pos_config.write({
            "order_note_ids": cls.order_note_tags.ids,
            "order_note_on_receipt": True,
        })

        cls.env["res.lang"]._activate_lang("ar_001")
        cls.env.ref("base.module_fuap_pos_order_notes")._update_translations(["ar_001"])
        cls.order_note_tags[2].with_context(lang="ar_001").name = "تم تجهيز الطلب"

    def _open_ui_in(self, lang):
        self.pos_user.lang = lang
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def test_full_order_note_flow_and_receipt(self):
        self._open_ui_in("en_US")

        self.start_pos_tour("fuap_pos_order_note_flow")
        order = self.env["pos.order"].search([
            ("config_id", "=", self.main_pos_config.id),
            ("state", "in", ["paid", "done"]),
        ], order="id desc", limit=1)
        self.assertEqual(order.order_note, "test note, Gluten free")

    def test_receipt_option_can_hide_order_note(self):
        self.main_pos_config.order_note_on_receipt = False
        self._open_ui_in("en_US")

        self.start_pos_tour("fuap_pos_order_note_hidden_receipt")

    def test_reprinted_receipt_contains_order_note(self):
        self._open_ui_in("en_US")

        self.start_pos_tour("fuap_pos_order_note_reprint")

    def test_order_note_popup_in_ltr(self):
        self._open_ui_in("en_US")

        self.start_pos_tour("fuap_pos_order_note_ltr")

    def test_order_note_popup_in_arabic_rtl(self):
        self._open_ui_in("ar_001")

        self.start_pos_tour("fuap_pos_order_note_rtl")
