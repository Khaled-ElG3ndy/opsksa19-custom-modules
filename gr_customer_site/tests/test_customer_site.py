# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestCustomerSite(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Site = cls.env['gr.customer.site']
        cls.partner = cls.env['res.partner'].create({'name': 'Acme Construction'})

    def _make_site(self, **kw):
        vals = {'name': 'Test Site', 'partner_id': self.partner.id}
        vals.update(kw)
        return self.Site.create(vals)

    def test_create_assigns_sequence_code(self):
        site = self._make_site()
        self.assertTrue(site.code.startswith('GR/SITE/'),
                        "Site code should come from the GR/SITE sequence")

    def test_partner_required(self):
        with self.assertRaises(Exception):
            # Missing required partner_id should fail at ORM level.
            self.Site.create({'name': 'No Partner Site'})

    def test_code_unique_per_company(self):
        s1 = self._make_site()
        # Forcing a duplicate code in the same company must fail the SQL constraint.
        with self.assertRaises(Exception):
            self.Site.create({
                'name': 'Dup', 'partner_id': self.partner.id, 'code': s1.code})

    def test_negative_kva_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_site(required_kva=-50.0)

    def test_negative_load_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_site(required_load_kw=-10.0)

    def test_gps_out_of_range_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_site(gps_latitude=120.0)
        with self.assertRaises(ValidationError):
            self._make_site(gps_longitude=-200.0)

    def test_gps_valid_allowed(self):
        site = self._make_site(gps_latitude=24.7136, gps_longitude=46.6753)  # Riyadh
        self.assertEqual(round(site.gps_latitude, 4), 24.7136)

    def test_smart_button_counts_default_zero(self):
        site = self._make_site()
        self.assertEqual(site.contract_count, 0)
        self.assertEqual(site.rental_order_count, 0)
        self.assertEqual(site.installed_generator_count, 0)
        self.assertEqual(site.hour_log_count, 0)
        self.assertEqual(site.maintenance_job_count, 0)

    def test_onchange_partner_prefills_contact(self):
        self.partner.write({'phone': '+966500000000', 'email': 'site@acme.test',
                            'city': 'Riyadh'})
        site = self.Site.new({'name': 'OC Site', 'partner_id': self.partner.id})
        site._onchange_partner_id()
        self.assertEqual(site.contact_name, 'Acme Construction')
        self.assertEqual(site.contact_phone, '+966500000000')
        self.assertEqual(site.contact_email, 'site@acme.test')
        self.assertEqual(site.city, 'Riyadh')
