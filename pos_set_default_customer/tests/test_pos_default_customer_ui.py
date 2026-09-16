# -*- coding: utf-8 -*-
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged('post_install', '-at_install')
class TestPosDefaultCustomerUi(TestPointOfSaleHttpCommon):
    """Drive a real Point of Sale session in the browser."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.default_customer = cls.env['res.partner'].create({
            'name': 'Default POS Customer',
        })
        cls.main_pos_config.default_customer_id = cls.default_customer

    def _open_ui_in(self, lang):
        """Put the cashier in ``lang`` and open the register.

        The language is activated rather than assumed: a database can be
        installed with only Arabic, in which case English is not merely unused
        but inactive, and a tour that silently fell back would be testing the
        wrong direction.
        """
        self.env['res.lang']._activate_lang(lang)
        self.pos_user.lang = lang
        self.main_pos_config.with_user(self.pos_user).open_ui()

    def test_default_customer_is_preselected_on_every_order(self):
        """Opening the register and starting the next order both preselect it."""
        self._open_ui_in('en_US')

        self.start_pos_tour('pos_default_customer_tour')

    def test_default_customer_survives_a_right_to_left_session(self):
        """The same thing holds for a cashier working in Arabic.

        Arabic flips the whole interface to RTL, so this is the run that proves
        nothing in the module depends on the reading direction. The tour asserts
        the direction it got, otherwise it would pass without testing anything.
        """
        self._open_ui_in('ar_001')

        self.start_pos_tour('pos_default_customer_rtl_tour')

    def test_default_customer_in_a_left_to_right_session(self):
        """The mirror of the RTL run, sharing its steps, as the control."""
        self._open_ui_in('en_US')

        self.start_pos_tour('pos_default_customer_ltr_tour')
