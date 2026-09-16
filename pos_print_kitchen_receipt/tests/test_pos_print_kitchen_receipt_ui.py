# Copyright 2026 Khaled ElGendy
# All rights reserved.

from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestPosPrintKitchenReceiptUi(TestPointOfSaleHttpCommon):
    """Print the kitchen receipt from a real browser and read what comes out."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Two internal product categories: one the kitchen cooks from, one the
        # bar serves. The exclusion setting is what tells them apart.
        cls.food_category = cls.env["product.category"].create({"name": "Kitchen Food"})
        cls.drinks_category = cls.env["product.category"].create({"name": "Kitchen Drinks"})

        cls.burger, cls.fries, cls.cola = cls.env["product.product"].create(
            [
                {
                    "name": "Kitchen Burger",
                    "available_in_pos": True,
                    "list_price": 20.0,
                    "taxes_id": False,
                    "categ_id": cls.food_category.id,
                },
                {
                    "name": "Kitchen Fries",
                    "available_in_pos": True,
                    "list_price": 8.0,
                    "taxes_id": False,
                    "categ_id": cls.food_category.id,
                },
                {
                    "name": "Kitchen Cola",
                    "available_in_pos": True,
                    "list_price": 5.0,
                    "taxes_id": False,
                    "categ_id": cls.drinks_category.id,
                },
            ]
        )

    def _configure(self, enabled=True, category_wise=True, excluded=None):
        self.main_pos_config.write(
            {
                "print_kitchen_receipt": enabled,
                "print_kitchen_receipt_categ": category_wise,
                "print_kitchen_categories_exclude_ids": [
                    (6, 0, (excluded or self.env["product.category"]).ids)
                ],
            }
        )
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def test_a_category_wise_receipt_groups_food_and_leaves_out_the_drinks(self):
        """The reference run: headings, exclusions, notes and quantities.

        This is the whole feature end to end — the button reaches the screen,
        the screen renders the receipt, and the configuration decides what is
        on it.
        """
        self._configure(category_wise=True, excluded=self.drinks_category)

        self.start_pos_tour("pos_print_kitchen_receipt_tour")

    def test_a_plain_receipt_lists_every_line_including_the_excluded_category(self):
        """Exclusions belong to category-wise mode only.

        Applying them to the flat receipt would quietly drop products from the
        kitchen's copy of the order, which is worse than printing too much.
        """
        self._configure(category_wise=False, excluded=self.drinks_category)

        self.start_pos_tour("pos_print_kitchen_receipt_flat_tour")

    def test_the_button_is_absent_when_the_point_of_sale_did_not_ask_for_it(self):
        """A per-POS setting that shows the button everywhere is not a setting."""
        self._configure(enabled=False)

        self.start_pos_tour("pos_print_kitchen_receipt_disabled_tour")

    def test_an_empty_order_is_refused_instead_of_printed_blank(self):
        """Nothing selected means a message, not a blank sheet of paper."""
        self._configure(category_wise=True, excluded=self.drinks_category)

        self.start_pos_tour("pos_print_kitchen_receipt_empty_order_tour")
