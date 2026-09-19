from lxml import etree

from odoo.tools import is_html_empty
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


# Every external layout Odoo 19 ships. Enumerated from the module's own
# inherited views would only ever confirm the module agrees with itself, so
# the list is written out and a test checks it against what web installs.
LAYOUTS = ("standard", "boxed", "bold", "striped", "folder", "wave", "bubble")


PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Wl2nWQAAAAASUVORK5CYII="
).encode()


# Run once the whole registry is up. These touch models other modules extend
# (res.company cascades into res.partner, mrp.bom into stock), and at this
# module's own position in the dependency graph those extensions have their
# NOT NULL columns in the database but not yet in the registry, so a plain
# create() fails on a column the ORM does not know to fill.
@tagged("post_install", "-at_install")
class TestDocumentLayoutHeader(TransactionCase):
    def test_layout_fields_write_through_to_company(self):
        company = self.env.company
        layout = self.env["base.document.layout"].create(
            {"company_id": company.id}
        )

        layout.write({"header_img": PNG_1X1, "footer_img": PNG_1X1})

        self.assertEqual(company.header_img, PNG_1X1)
        self.assertEqual(company.footer_img, PNG_1X1)

    def test_custom_header_and_footer_render(self):
        company = self.env.company
        company.write({"header_img": PNG_1X1, "footer_img": PNG_1X1})
        values = {"company": company, "report_type": "pdf"}

        header = str(self.env["ir.qweb"]._render(
            "document_layout_header.full_width_header", values))
        footer = str(self.env["ir.qweb"]._render(
            "document_layout_header.full_width_footer", values))

        self.assertIn("o_full_width_header", header)
        self.assertIn("data:image/png;base64", header)
        self.assertIn("o_full_width_footer", footer)
        self.assertIn('class="page"', footer)
        self.assertIn('class="topage"', footer)

    def test_all_supported_external_layouts_include_custom_blocks(self):
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                view = self.env.ref(
                    f"document_layout_header.external_layout_{layout}_inherit"
                )
                arch = etree.tostring(
                    view._get_combined_arch(), encoding="unicode"
                )
                self.assertIn("document_layout_header.full_width_header", arch)
                self.assertIn("document_layout_header.full_width_footer", arch)
                self.assertIn("not company.header_img", arch)
                self.assertIn("not company.footer_img", arch)

    # -- the layouts as they are actually printed --------------------------

    def _render_layout(self, company, layout="standard", report_type="pdf"):
        """Render one of the four external layouts the way a report does."""
        # The field points at the layout's view, not at the report.layout record.
        company.external_report_layout_id = self.env.ref(
            f"web.external_layout_{layout}"
        )
        return str(
            self.env["ir.qweb"]._render(
                "web.external_layout",
                {
                    "company": company,
                    "o": company.partner_id,
                    "report_type": report_type,
                    # Report rendering injects this helper into the context; the
                    # layouts call it and raise KeyError without it.
                    "is_html_empty": is_html_empty,
                },
            )
        )

    @staticmethod
    def _blocks(tree, klass):
        """Elements carrying ``klass`` as a whole class, not as a substring.

        ``contains(@class, 'footer')`` also matches ``o_footer_content``, which
        sits inside the very block being counted.
        """
        return tree.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), "
            f"' {klass} ')]"
        )

    def test_a_company_with_images_prints_them_instead_of_the_core_header(self):
        """The whole point of the module, asserted through a real layout.

        Rendering the templates on their own says nothing about whether the
        core header actually stands down, which is the half that broke on every
        previous release.
        """
        company = self.env.company
        company.write({"header_img": PNG_1X1, "footer_img": PNG_1X1})

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                html = self._render_layout(company, layout)
                tree = etree.HTML(html)

                self.assertTrue(self._blocks(tree, "o_full_width_header"))
                self.assertTrue(self._blocks(tree, "o_full_width_footer"))
                # Exactly one header and one footer: the core blocks stood down
                # rather than printing above or below the images.
                self.assertEqual(len(self._blocks(tree, "header")), 1)
                self.assertEqual(len(self._blocks(tree, "footer")), 1)

    def test_a_company_without_images_keeps_the_core_header(self):
        """The t-if is an inversion, so its false branch needs asserting too."""
        company = self.env.company
        company.write({"header_img": False, "footer_img": False})

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                tree = etree.HTML(self._render_layout(company, layout))

                self.assertFalse(self._blocks(tree, "o_full_width_header"))
                self.assertFalse(self._blocks(tree, "o_full_width_footer"))
                self.assertEqual(len(self._blocks(tree, "header")), 1)
                self.assertEqual(len(self._blocks(tree, "footer")), 1)

    def test_only_the_company_that_set_an_image_gets_one(self):
        """Images belong to a company, and a report names its own company."""
        with_images = self.env.company
        with_images.write({"header_img": PNG_1X1, "footer_img": PNG_1X1})
        without = self.env["res.company"].create({"name": "No Letterhead Co"})

        self.assertIn("o_full_width_header", self._render_layout(with_images))
        self.assertNotIn("o_full_width_header", self._render_layout(without))

    def test_the_page_counter_is_printed_on_paper_only(self):
        """`page`/`topage` are wkhtmltopdf substitutions and mean nothing in HTML."""
        company = self.env.company
        company.write({"header_img": PNG_1X1, "footer_img": PNG_1X1})

        self.assertIn('class="page"', self._render_layout(company, report_type="pdf"))
        self.assertNotIn('class="page"', self._render_layout(company, report_type="html"))

    def test_every_layout_odoo_ships_is_covered(self):
        """A layout added by Odoo and not hooked here fails silently.

        That is exactly how folder, wave and bubble went unnoticed: a company
        that picked one of them simply got the stock header back, with nothing
        anywhere to say the setting had been ignored.
        """
        shipped = {
            layout.view_id.key.rsplit("external_layout_", 1)[-1]
            for layout in self.env["report.layout"].search([])
            if layout.view_id.key and "external_layout_" in layout.view_id.key
        }

        self.assertEqual(
            shipped - set(LAYOUTS),
            set(),
            "an external layout exists that this module does not hook into",
        )
        for layout in shipped:
            self.assertTrue(
                self.env.ref(
                    f"document_layout_header.external_layout_{layout}_inherit",
                    raise_if_not_found=False,
                ),
                f"no inherited view for the {layout} layout",
            )
