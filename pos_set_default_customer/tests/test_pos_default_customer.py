# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestPosDefaultCustomer(TestPoSCommon):
    """Server side of the Point of Sale default customer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.default_customer = cls.env['res.partner'].create({
            'name': 'Default POS Customer',
        })

    # -- configuration ----------------------------------------------------

    def test_default_customer_is_optional(self):
        """A Point of Sale with no default customer keeps working untouched."""
        self.assertFalse(self.config.default_customer_id)

    def test_default_customer_is_stored_per_config(self):
        """Each Point of Sale carries its own default customer."""
        other_config = self.config.copy({'name': 'Second Shop'})

        self.config.default_customer_id = self.default_customer
        other_config.default_customer_id = self.other_customer

        self.assertEqual(self.config.default_customer_id, self.default_customer)
        self.assertEqual(other_config.default_customer_id, self.other_customer)

    def test_deleting_the_customer_clears_the_config(self):
        """Removing the partner must not leave a dangling reference."""
        throwaway = self.env['res.partner'].create({'name': 'Throwaway Customer'})
        self.config.default_customer_id = throwaway

        throwaway.unlink()

        self.assertFalse(self.config.default_customer_id)

    def test_customer_of_another_company_is_rejected(self):
        """check_company keeps a foreign company's partner off the config."""
        other_company = self.env['res.company'].create({'name': 'Other Company'})
        foreign_customer = self.env['res.partner'].create({
            'name': 'Foreign Customer',
            'company_id': other_company.id,
        })

        with self.assertRaises(UserError):
            self.config.default_customer_id = foreign_customer

    def test_company_less_customer_is_accepted(self):
        """A partner shared across companies is a valid default."""
        self.assertFalse(self.default_customer.company_id)

        self.config.default_customer_id = self.default_customer

        self.assertEqual(self.config.default_customer_id, self.default_customer)

    # -- settings page ----------------------------------------------------

    def test_settings_field_writes_through_to_the_config(self):
        """Saving the settings page stores the customer on the Point of Sale."""
        settings = self.env['res.config.settings'].create({
            'pos_config_id': self.config.id,
            'pos_default_customer_id': self.default_customer.id,
        })
        settings.execute()

        self.assertEqual(self.config.default_customer_id, self.default_customer)

    def test_settings_field_reads_back_the_config(self):
        """Opening the settings page shows the customer already configured."""
        self.config.default_customer_id = self.default_customer

        settings = self.env['res.config.settings'].create({
            'pos_config_id': self.config.id,
        })

        self.assertEqual(settings.pos_default_customer_id, self.default_customer)

    def test_settings_field_can_clear_the_customer(self):
        """Emptying the field on the settings page clears the config."""
        self.config.default_customer_id = self.default_customer

        settings = self.env['res.config.settings'].create({
            'pos_config_id': self.config.id,
            'pos_default_customer_id': False,
        })
        settings.execute()

        self.assertFalse(self.config.default_customer_id)

    # -- session loading --------------------------------------------------

    def _loaded_partner_ids(self):
        records = self.env['res.partner']._load_pos_data_search_read(
            {'pos.order': []}, self.config,
        )
        return [record['id'] for record in records]

    def _create_fillers(self):
        """Partners that sort ahead of the default customer, to fill the cap."""
        return self.env['res.partner'].create([
            {'name': 'AAA Filler Customer %02d' % index} for index in range(5)
        ])

    def _cap_partner_loading(self, count):
        """Shrink the cap on how many partners a session preloads."""
        self.env['ir.config_parameter'].sudo().set_param(
            'point_of_sale.limited_customer_count', count,
        )

    def test_customer_is_shipped_to_the_session(self):
        """The configured customer reaches the browser."""
        self.config.default_customer_id = self.default_customer

        self.assertIn(self.default_customer.id, self._loaded_partner_ids())

    def test_customer_is_shipped_only_once(self):
        """A customer the session already loads is not sent twice."""
        self.config.default_customer_id = self.default_customer

        loaded_ids = self._loaded_partner_ids()

        self.assertEqual(loaded_ids.count(self.default_customer.id), 1)

    def test_customer_is_shipped_past_the_partner_cap(self):
        """Loading is capped at the most-used partners; the default beats it."""
        self._create_fillers()
        self.config.default_customer_id = self.default_customer
        self._cap_partner_loading(1)

        loaded_ids = self._loaded_partner_ids()

        self.assertIn(self.default_customer.id, loaded_ids)
        self.assertLess(
            len(loaded_ids), 5,
            "the cap still applies to every other customer",
        )

    def test_customer_is_shipped_past_a_narrowed_domain(self):
        """Another module ANDing a restriction onto the domain cannot hide it.

        ``pos_customer_restrict`` does exactly this, so reproduce the shape of
        its override rather than depending on that module being installed.
        """
        self.config.default_customer_id = self.default_customer
        partner_class = self.env.registry['res.partner']
        stock_domain = partner_class._load_pos_data_domain

        def narrowed_domain(records, data, config):
            return stock_domain(records, data, config) + [
                ('id', '!=', self.default_customer.id),
            ]

        self.patch(partner_class, '_load_pos_data_domain', narrowed_domain)

        self.assertNotIn(
            self.default_customer.id,
            [record['id'] for record in self.env['res.partner'].search_read(
                narrowed_domain(self.env['res.partner'], {'pos.order': []}, self.config),
                ['id'],
            )],
            "sanity check: the narrowed domain really does exclude the customer",
        )
        self.assertIn(self.default_customer.id, self._loaded_partner_ids())

    def test_the_customer_is_the_only_thing_added(self):
        """Setting a default customer adds that customer and nothing else.

        The cap has to be in play for this to say anything: on a small address
        book the session already loads every partner, default one included.
        """
        self._create_fillers()
        self._cap_partner_loading(1)

        self.config.default_customer_id = self.default_customer
        with_default = set(self._loaded_partner_ids())

        self.config.default_customer_id = False
        without_default = set(self._loaded_partner_ids())

        self.assertEqual(with_default - without_default, {self.default_customer.id})

    def test_customer_is_in_the_limited_partner_hook(self):
        """The core hook other modules read from also reports the customer."""
        self._create_fillers()
        self.config.default_customer_id = self.default_customer
        self._cap_partner_loading(1)

        partner_ids = self.config.get_limited_partners_loading()

        self.assertIn((self.default_customer.id,), partner_ids)

    def test_limited_partner_hook_has_no_duplicate(self):
        """The customer is not appended when the hook already returned it."""
        self.config.default_customer_id = self.default_customer

        partner_ids = self.config.get_limited_partners_loading()

        self.assertEqual(partner_ids.count((self.default_customer.id,)), 1)

    def test_config_field_is_sent_to_the_browser(self):
        """The POS client can read the customer off its config."""
        self.config.default_customer_id = self.default_customer

        records = self.env['pos.config']._load_pos_data_read(self.config, self.config)

        self.assertEqual(records[0]['default_customer_id'], self.default_customer.id)

    def test_relation_is_declared_for_the_browser(self):
        """The client-side model graph knows the field points at a partner."""
        self.config.default_customer_id = self.default_customer
        self.open_new_session()

        relations = self.pos_session.load_data_params()['pos.config']['relations']

        self.assertEqual(relations['default_customer_id']['type'], 'many2one')
        self.assertEqual(relations['default_customer_id']['relation'], 'res.partner')

    def test_customer_is_loaded_by_a_real_session(self):
        """End to end on the server: open a session and read what it ships."""
        self._create_fillers()
        self.config.default_customer_id = self.default_customer
        self._cap_partner_loading(1)
        self.open_new_session()

        data = self.pos_session.load_data([])

        loaded_ids = {record['id'] for record in data['res.partner']}
        self.assertIn(self.default_customer.id, loaded_ids)
        self.assertEqual(
            data['pos.config'][0]['default_customer_id'],
            self.default_customer.id,
        )

    # -- alongside the module that narrows the address book ----------------

    def _skip_without_customer_restrict(self):
        if 'is_available_in_pos' not in self.env['res.partner']._fields:
            self.skipTest('pos_customer_restrict is not installed')

    def test_the_default_customer_survives_pos_customer_restrict(self):
        """The simulated narrowing above is exercised against the real module.

        Both modules are installed together in production, and each one's
        correctness here rests on the other's ordering. A stand-in domain proves
        the mechanism; only the real module proves the pair.
        """
        self._skip_without_customer_restrict()
        self.default_customer.is_available_in_pos = False
        self.config.default_customer_id = self.default_customer

        self.assertIn(self.default_customer.id, self._loaded_partner_ids())

    def test_restricted_customers_are_still_kept_out(self):
        """Forcing one customer through must not open the door for the rest."""
        self._skip_without_customer_restrict()
        hidden = self.env['res.partner'].create({
            'name': 'Not For The Register',
            'is_available_in_pos': False,
        })
        self.config.default_customer_id = self.default_customer

        self.assertNotIn(hidden.id, self._loaded_partner_ids())

