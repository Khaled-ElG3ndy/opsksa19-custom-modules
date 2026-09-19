from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


# Run once the whole registry is up. These touch models other modules extend
# (res.company cascades into res.partner, mrp.bom into stock), and at this
# module's own position in the dependency graph those extensions have their
# NOT NULL columns in the database but not yet in the registry, so a plain
# create() fails on a column the ORM does not know to fill.
@tagged("post_install", "-at_install")
class TestBomRecipe(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.finished = cls.env["product.product"].create(
            {"name": "Recipe Finished Product", "uom_id": cls.kg.id}
        )
        cls.component = cls.env["product.product"].create(
            {"name": "Recipe Component", "uom_id": cls.kg.id}
        )

    def _make_bom(self, **values):
        vals = {
            "product_tmpl_id": self.finished.product_tmpl_id.id,
            "product_uom_id": self.kg.id,
            "product_qty": 1.0,
            "is_recipe": True,
            "yield_percentage": 0.10,
            "bom_line_ids": [Command.create({
                "product_id": self.component.id,
                "product_qty": 10.0,
                "product_uom_id": self.kg.id,
            })],
        }
        vals.update(values)
        return self.env["mrp.bom"].create(vals)

    def test_recipe_total_and_yield_onchange(self):
        bom = self._make_bom()

        self.assertEqual(bom.bom_qty, 10.0)
        bom._onchange_total_product_qty()
        self.assertEqual(bom.product_qty, 9.0)

        bom.bom_line_ids.product_qty = 20.0
        self.assertEqual(bom.bom_qty, 20.0)
        bom._onchange_total_product_qty()
        self.assertEqual(bom.product_qty, 18.0)

    def test_non_recipe_keeps_standard_quantity(self):
        bom = self._make_bom(is_recipe=False, product_qty=4.0)
        bom._onchange_total_product_qty()
        self.assertEqual(bom.product_qty, 4.0)

    def test_recipe_rejects_invalid_yield_loss(self):
        for value in (-0.01, 1.0, 1.01):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self._make_bom(yield_percentage=value)

    def test_recipe_requires_identical_line_uom(self):
        unit_component = self.env["product.product"].create(
            {"name": "Unit Recipe Component", "uom_id": self.unit.id}
        )
        with self.assertRaises(ValidationError):
            self._make_bom(bom_line_ids=[Command.create({
                "product_id": unit_component.id,
                "product_qty": 1.0,
                "product_uom_id": self.unit.id,
            })])

    def test_the_uom_rule_holds_when_a_line_is_edited_on_its_own(self):
        """A rule that only holds in the form view is not a rule.

        The constraint is declared on ``mrp.bom`` against ``bom_line_ids``, and
        ``@api.constrains`` ignores dotted names, so writing straight to the
        line -- an import, a data file, another module -- reached none of it.
        """
        bom = self._make_bom()

        with self.assertRaises(ValidationError):
            bom.bom_line_ids[0].product_uom_id = self.unit

    def test_a_line_on_a_plain_bom_may_use_any_uom(self):
        """The rule belongs to recipes; ordinary BoMs are left alone."""
        bom = self._make_bom(is_recipe=False, yield_percentage=0.0)

        bom.bom_line_ids[0].product_uom_id = self.unit

        self.assertEqual(bom.bom_line_ids[0].product_uom_id, self.unit)

    def test_adding_a_matching_line_to_a_recipe_is_still_allowed(self):
        """The new check must not reject what the rule permits."""
        bom = self._make_bom()

        bom.write({
            "bom_line_ids": [Command.create({
                "product_id": self.component.id,
                "product_qty": 5.0,
                "product_uom_id": self.kg.id,
            })],
        })

        self.assertEqual(len(bom.bom_line_ids), 2)
        self.assertEqual(bom.bom_qty, 15.0)
