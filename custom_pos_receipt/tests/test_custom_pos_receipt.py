# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import file_open
from odoo.tools.translate import babel_extract_qweb, code_translations

# The two templates this module prints from. Terms are read back out of them
# rather than listed here, so a label added later cannot slip past the
# translation test below.
TEMPLATES = (
    'custom_pos_receipt/static/src/app/screens/receipt_screen/receipt/receipt_header.xml',
    'custom_pos_receipt/static/src/app/screens/receipt_screen/receipt/order_receipt.xml',
)

# Every Arabic locale falls back through ar.po, so both files have to carry the
# receipt labels for a session in, say, ar_SY to print them.
ARABIC_LANGS = ('ar', 'ar_001')


def receipt_terms():
    """Every translatable term the receipt templates introduce."""
    terms = []
    for template in TEMPLATES:
        with file_open(template, mode='rb') as template_file:
            terms += [term for _lineno, _func, term, _comments
                      in babel_extract_qweb(template_file, [], [], {})]
    return terms


@tagged('post_install', '-at_install')
class TestCustomPosReceipt(TransactionCase):
    """The receipt's server side: the data it is fed and the words it prints."""

    # -- what the Point of Sale has to send the receipt -------------------

    def test_the_receipt_is_given_the_client_name_it_prints(self):
        """The client line reads name and parent_name off the loaded partner.

        Both are loaded by point_of_sale today. If a release stopped sending
        one, the line would quietly print nothing at all, so the dependency is
        worth stating out loud.
        """
        config = self.env['pos.config'].create({'name': 'Receipt Test Shop'})

        fields = self.env['res.partner']._load_pos_data_fields(config)

        self.assertIn('name', fields)
        self.assertIn('parent_name', fields)

    def test_the_receipt_is_given_the_tax_rate_it_prints(self):
        """The VAT% column reads amount_type and amount off the loaded taxes.

        Without them the column would fall back to a rate derived from the
        amounts, which is right but not what a percentage tax should print.
        """
        config = self.env['pos.config'].create({'name': 'Receipt Tax Test Shop'})

        fields = self.env['account.tax']._load_pos_data_fields(config)

        self.assertIn('amount_type', fields)
        self.assertIn('amount', fields)

    # -- the figures the four columns hold --------------------------------

    def test_the_vat_columns_hold_the_tax_engines_own_figures(self):
        """A 97.75 sale at 15% included splits into 85.00 and 12.75.

        These are the numbers the browser tests read off the printed receipt.
        Pinning them here means a change in the tax engine is reported as a
        tax failure rather than as an unexplained browser one.
        """
        vat_15 = self.env['account.tax'].create({
            'name': 'VAT 15%',
            'amount_type': 'percent',
            'amount': 15.0,
            'price_include_override': 'tax_included',
        })

        computed = vat_15.compute_all(97.75, quantity=1)

        self.assertEqual(self.env.company.currency_id.round(computed['total_excluded']), 85.00)
        self.assertEqual(self.env.company.currency_id.round(computed['taxes'][0]['amount']), 12.75)
        self.assertEqual(self.env.company.currency_id.round(computed['total_included']), 97.75)

    # -- the words the receipt prints -------------------------------------

    def test_the_receipt_introduces_the_labels_it_is_meant_to(self):
        """The receipt gains a client label and the four VAT column headers."""
        self.assertEqual(
            sorted(receipt_terms()),
            sorted(['Client:', 'VAT%', 'VAT', 'ExVAT', 'Total']),
        )

    def test_every_receipt_label_is_translated_into_arabic(self):
        """No label may reach an Arabic receipt in English.

        The terms are extracted from the templates, so adding a label without
        translating it fails here instead of showing up on a customer's ticket.
        """
        for lang in ARABIC_LANGS:
            translations = {
                message['id']: message['string']
                for message in code_translations.get_web_translations(
                    'custom_pos_receipt', lang,
                )['messages']
            }
            for term in receipt_terms():
                with self.subTest(lang=lang, term=term):
                    self.assertTrue(
                        translations.get(term),
                        f'"{term}" has no Arabic translation in i18n/{lang}.po',
                    )
                    self.assertNotEqual(translations[term], term)

    def test_the_arabic_labels_are_the_ones_the_receipt_shows(self):
        """The exact strings an Arabic cashier reads, pinned.

        The browser tests look for these on the printed receipt; keeping the
        pair in step is what makes a wording change a deliberate edit in two
        places rather than a silently failing tour.
        """
        translations = {
            message['id']: message['string']
            for message in code_translations.get_web_translations(
                'custom_pos_receipt', 'ar_001',
            )['messages']
        }

        self.assertEqual(translations['Client:'], 'العميل:')
        self.assertEqual(translations['VAT%'], 'نسبة الضريبة')
        self.assertEqual(translations['VAT'], 'الضريبة')
        self.assertEqual(translations['ExVAT'], 'قبل الضريبة')
        self.assertEqual(translations['Total'], 'الإجمالي')
