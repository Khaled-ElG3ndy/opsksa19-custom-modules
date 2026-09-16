# -*- coding: utf-8 -*-
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged('post_install', '-at_install')
class TestCustomPosReceiptUi(TestPointOfSaleHttpCommon):
    """Sell something in a real browser and read the receipt that comes out."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # One tax group holding every VAT rate, the way the Saudi chart puts
        # 15% and the zero-rated taxes in a single "VAT Total Amount" group.
        # The receipt has to tell those rates apart regardless.
        cls.vat_group = cls.env['account.tax.group'].create({
            'name': 'VAT Total Amount',
            'company_id': cls.env.company.id,
        })

        # A 15% VAT included in the price: 97.75 on the shelf is 85.00 plus
        # 12.75 of tax, which is the sale the receipt is expected to summarise.
        cls.vat_15 = cls.env['account.tax'].create({
            'name': 'VAT 15%',
            'amount_type': 'percent',
            'amount': 15.0,
            'price_include_override': 'tax_included',
            'tax_group_id': cls.vat_group.id,
            'sequence': 1,
            'company_id': cls.env.company.id,
        })
        cls.corner_desk = cls.env['product.template'].create({
            'name': 'Corner Desk Left Sit',
            'available_in_pos': True,
            'list_price': 97.75,
            'taxes_id': [(6, 0, cls.vat_15.ids)],
        })
        cls.billy_fox = cls.env['res.partner'].create({
            'name': 'Billy Fox',
            'city': 'San Francisco',
        })

        # A second rate, so an order can carry two at once.
        cls.vat_5 = cls.env['account.tax'].create({
            'name': 'VAT 5%',
            'amount_type': 'percent',
            'amount': 5.0,
            'price_include_override': 'tax_included',
            'tax_group_id': cls.vat_group.id,
            'sequence': 2,
            'company_id': cls.env.company.id,
        })
        cls.reduced_rate_item = cls.env['product.template'].create({
            'name': 'Reduced Rate Item',
            'available_in_pos': True,
            'list_price': 105.00,
            'taxes_id': [(6, 0, cls.vat_5.ids)],
        })

        # Zero-rated goods, in that same group: a Saudi receipt has to show
        # them as taxed at 0% rather than as untaxed.
        cls.vat_0 = cls.env['account.tax'].create({
            'name': 'VAT 0%',
            'amount_type': 'percent',
            'amount': 0.0,
            'price_include_override': 'tax_included',
            'tax_group_id': cls.vat_group.id,
            'sequence': 3,
            'company_id': cls.env.company.id,
        })
        cls.zero_rated_item = cls.env['product.template'].create({
            'name': 'Zero Rated Item',
            'available_in_pos': True,
            'list_price': 50.00,
            'taxes_id': [(6, 0, cls.vat_0.ids)],
        })

        # A tax with no percentage of its own, to exercise the rate the
        # receipt has to work back out of the amounts.
        cls.fixed_duty = cls.env['account.tax'].create({
            'name': 'Fixed Duty',
            'amount_type': 'fixed',
            'amount': 10.0,
            'price_include_override': 'tax_excluded',
            'company_id': cls.env.company.id,
        })
        cls.fixed_duty_item = cls.env['product.template'].create({
            'name': 'Fixed Duty Item',
            'available_in_pos': True,
            'list_price': 100.00,
            'taxes_id': [(6, 0, cls.fixed_duty.ids)],
        })

        # A contact under a company: the receipt names both.
        cls.deco_addict = cls.env['res.partner'].create({
            'name': 'Deco Addict',
            'is_company': True,
        })
        cls.lily_fox = cls.env['res.partner'].create({
            'name': 'Lily Fox',
            'parent_id': cls.deco_addict.id,
        })

        # pos_customer_restrict, installed alongside this module in production,
        # loads only partners flagged for the register. Without the flag these
        # customers never reach the session and every tour below fails looking
        # for one -- a failure about this module that has nothing to do with it.
        if 'is_available_in_pos' in cls.env['res.partner']._fields:
            (cls.billy_fox | cls.deco_addict | cls.lily_fox).write({
                'is_available_in_pos': True,
            })

    def _open_register_in(self, lang):
        """Put the cashier in ``lang`` and open the register.

        The language is activated rather than assumed: a database can be
        installed without Arabic, and a tour that silently fell back to English
        would report a passing right-to-left run while testing nothing of the
        sort.
        """
        self.env['res.lang']._activate_lang(lang)
        self.pos_user.lang = lang
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def test_the_receipt_names_the_client_and_summarises_the_vat(self):
        """The English receipt: labelled client line and the VAT table."""
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_tour')

    def test_an_arabic_cashier_gets_a_mirrored_translated_receipt(self):
        """The same receipt in Arabic: mirrored, translated, same figures.

        Arabic flips the interface, and the receipt declares its own direction
        on top of that, so this is the run that proves the two additions travel
        with the language instead of being pinned left to right.
        """
        self._open_register_in('ar_001')

        self.start_pos_tour('custom_pos_receipt_rtl_tour')

    # -- the orders that would break a happy-path receipt ------------------

    def test_a_walk_in_customer_gets_a_receipt_with_no_client_line(self):
        """No customer on the order means no client line, and no blank label."""
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_no_customer_tour')

    def test_an_untaxed_order_prints_no_vat_summary(self):
        """A table of zeroes would be worse than no table."""
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_untaxed_tour')

    def test_two_rates_in_one_tax_group_get_a_row_each(self):
        """Rates sharing a tax group are still told apart.

        This is the Saudi shape: 15% and the reduced rates all sit in one
        "VAT Total Amount" group. Summarising per group would print a single
        blended rate for the order, which is why the table is built per tax.
        """
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_multi_vat_tour')

    def test_zero_rated_goods_are_shown_as_taxed_at_zero(self):
        """Zero-rated is not untaxed, and the receipt has to say so."""
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_zero_rated_tour')

    def test_a_contact_is_printed_under_the_company_it_belongs_to(self):
        """The company the customer belongs to stays on the receipt.

        The core receipt named it before this module took that line over, so
        dropping it would be a quiet regression rather than a design choice.
        """
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_company_contact_tour')

    def test_a_tax_with_no_percentage_still_prints_a_rate(self):
        """A fixed duty has no rate to declare, so one is derived.

        The derived figure can only ever agree with the VAT and ExVAT columns
        printed beside it, which is what keeps the row readable instead of
        blank.
        """
        self._open_register_in('en_US')

        self.start_pos_tour('custom_pos_receipt_fixed_tax_tour')
