# -*- coding: utf-8 -*-
import base64
from datetime import date, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

_SIG = base64.b64encode(b'sublet-test-signature')


@tagged('post_install', '-at_install')
class TestSublet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Ag = cls.env['gr.sublet.agreement']
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.vendor = cls.env['res.partner'].create({'name': 'Sublet Vendor'})
        cls.customer = cls.env['res.partner'].create({'name': 'Sublet Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Sublet Site', 'partner_id': cls.customer.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Sublet GM', 'login': 'sublet_gm', 'email': 'sgm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})
        cls.rent_service = cls.env['product.product'].create({
            'name': 'Genset Rent-in (monthly)', 'type': 'service',
            'purchase_ok': True, 'standard_price': 3000.0})
        Tax = cls.env['account.tax']
        cls.tax = Tax.search([
            ('type_tax_use', '=', 'sale'), ('amount_type', '=', 'percent'),
            ('amount', '=', 15.0),
            ('company_id', '=', cls.env.company.id)], limit=1) or Tax.create({
                'name': 'VAT 15% (Sales)', 'amount': 15.0,
                'amount_type': 'percent', 'type_tax_use': 'sale',
                'company_id': cls.env.company.id})
        # a rented-in unit (M11 owner flag)
        cls.rented_asset = cls.Asset.create({
            'name': 'Rented Gen', 'pm_interval_hours': 2000.0,
            'owner_type': 'rented_in', 'owner_partner_id': cls.vendor.id})
        cls.owned_asset = cls.Asset.create({
            'name': 'Owned Gen', 'pm_interval_hours': 2000.0})

    def _agreement(self, **kw):
        vals = {'asset_id': self.rented_asset.id, 'vendor_id': self.vendor.id,
                'rent_in_product_id': self.rent_service.id,
                'rent_in_amount': 3000.0,
                'date_start': date.today(),
                'date_end': date.today() + timedelta(days=30)}
        vals.update(kw)
        return self.Ag.create(vals)

    def _contract(self):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0})
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _monthly_contract(self, base_monthly_rate=1000.0):
        c = self.env['gr.rental.contract'].create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_type': 'monthly_with_included_hours',
            'included_hours_per_day': 8.0,
            'max_hours_per_day': 0.0,
            'base_monthly_rate': base_monthly_rate,
            'hourly_rate': 0.0,
            'overtime_hour_rate': 0.0,
            'violation_hour_rate': 0.0,
        })
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _rentout_order(self, agreement, contract, explicit_sublet=True):
        start = fields.Datetime.to_datetime(fields.Date.context_today(self.env.user))
        vals = {
            'partner_id': self.customer.id,
            'site_id': self.site.id,
            'contract_id': contract.id,
            'asset_id': self.rented_asset.id,
            'date_requested': start,
            'planned_dispatch_datetime': start,
            'planned_return_datetime': start + timedelta(days=10),
        }
        if explicit_sublet:
            vals['sublet_agreement_id'] = agreement.id
        order = self.Order.create(vals)
        self._confirm_order(order)
        order.action_reserve()
        insp = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id,
            'mode': 'delivery',
        })
        insp._populate_default_checklist()
        self._approve_order_if_needed(insp)
        insp.action_pass()
        order.action_dispatch()
        order.start_meter_reading = 0.0
        order.action_install()
        order.action_start_rental()
        return order

    def _approve_order_if_needed(self, order):
        if 'approval_state' not in order._fields:
            return
        with patch.object(type(order), '_render_approval_pdf',
                          return_value=b'%PDF-sublet-test'):
            if not order.current_approval_document_id:
                order._generate_approval_copy(language='en_US')
            order.approval_signature = _SIG
            order.approval_signed_by = 'Sublet Tester'
            order.action_approve_by_signature()

    def _confirm_order(self, order):
        self._approve_order_if_needed(order)
        order.action_confirm()

    def _approved_log(self, order, current=80.0):
        base = fields.Date.context_today(self.env['gr.hour.log'])
        log = self.env['gr.hour.log'].create({
            'rental_order_id': order.id,
            'current_meter_reading': current,
            'reading_date': base + timedelta(days=10),
            'previous_meter_reading': 0.0,
            'previous_reading_date': base,
        })
        log.action_submit()
        log.with_user(self.gm).action_approve()
        return log

    def _account(self, account_type):
        return self.env['account.account'].search([
            ('account_type', '=', account_type),
            ('company_ids', 'in', self.env.company.id),
        ], limit=1)

    def _general_journal(self):
        return self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    # ---------- sequence + onchange ----------
    def test_sequence_generation(self):
        ag = self._agreement()
        self.assertTrue(ag.name.startswith('GR/SUB/'))

    def test_vendor_defaults_from_owner(self):
        ag = self.Ag.new({'asset_id': self.rented_asset.id})
        ag._onchange_asset()
        self.assertEqual(ag.vendor_id, self.vendor)

    # ---------- rent-in PO born linked ----------
    def test_raise_rent_in_po(self):
        ag = self._agreement()
        ag.action_generate_rent_in_po()
        self.assertEqual(ag.state, 'committed')
        self.assertTrue(ag.purchase_order_id)
        self.assertEqual(ag.purchase_order_id.origin, ag.name)
        self.assertEqual(ag.purchase_line_id.price_unit, 3000.0)

    def test_po_requires_product(self):
        ag = self._agreement(rent_in_product_id=False)
        with self.assertRaises(UserError):
            ag.action_generate_rent_in_po()

    def test_only_draft_raises_po(self):
        ag = self._agreement()
        ag.action_generate_rent_in_po()
        with self.assertRaises(UserError):
            ag.action_generate_rent_in_po()

    def test_rent_in_product_must_be_service(self):
        stock_product = self.env['product.product'].create({
            'name': 'Rented Generator Stock Product',
            'type': 'consu',
            'purchase_ok': True,
        })
        with self.assertRaises(ValidationError) as caught:
            self._agreement(rent_in_product_id=stock_product.id)
        self.assertIn('must be a service product', str(caught.exception))

    def test_rent_in_product_cannot_use_fixed_asset_account(self):
        fixed_account = self._account('asset_fixed')
        if not fixed_account:
            self.skipTest("No fixed-asset account in this test chart.")
        asset_product = self.env['product.product'].create({
            'name': 'Capitalized Rent-in Service',
            'type': 'service',
            'purchase_ok': True,
            'property_account_expense_id': fixed_account.id,
        })
        with self.assertRaises(ValidationError) as caught:
            self._agreement(rent_in_product_id=asset_product.id)
        self.assertIn('fixed-asset/depreciation account', str(caught.exception))

    def test_po_generation_rechecks_rent_in_product_account(self):
        fixed_account = self._account('asset_fixed')
        if not fixed_account:
            self.skipTest("No fixed-asset account in this test chart.")
        ag = self._agreement(rent_in_product_id=self.rent_service.id)
        self.rent_service.property_account_expense_id = fixed_account
        with self.assertRaises(ValidationError) as caught:
            ag.action_generate_rent_in_po()
        self.assertIn('fixed-asset/depreciation account', str(caught.exception))

    def test_rent_in_product_cannot_have_asset_category(self):
        if 'asset_category_id' not in self.rent_service.product_tmpl_id._fields:
            self.skipTest("Accounting asset categories are not installed.")
        fixed_account = self._account('asset_fixed')
        depreciation_account = (
            self._account('expense_depreciation') or self._account('expense'))
        journal = self._general_journal()
        if not fixed_account or not depreciation_account or not journal:
            self.skipTest("Test chart lacks accounts/journal for asset category.")
        asset_category = self.env['account.asset.category'].create({
            'name': 'Blocked Rent-in Asset Category',
            'account_asset_id': fixed_account.id,
            'account_depreciation_id': fixed_account.id,
            'account_depreciation_expense_id': depreciation_account.id,
            'journal_id': journal.id,
            'company_id': self.env.company.id,
            'method_number': 5,
            'method_period': 1,
        })
        asset_product = self.env['product.product'].create({
            'name': 'Rent-in Service With Asset Category',
            'type': 'service',
            'purchase_ok': True,
            'asset_category_id': asset_category.id,
        })
        with self.assertRaises(ValidationError) as caught:
            self._agreement(rent_in_product_id=asset_product.id)
        self.assertIn('Asset Category', str(caught.exception))

    # ---------- margin ----------
    def test_cost_in_from_amount(self):
        ag = self._agreement(rent_in_amount=2500.0)
        ag._compute_margin()
        self.assertEqual(ag.cost_in, 2500.0)
        self.assertEqual(ag.extra_direct_cost, 0.0)
        self.assertEqual(ag.total_cost, 2500.0)
        # no revenue yet
        self.assertEqual(ag.revenue_out, 0.0)
        self.assertEqual(ag.margin, -2500.0)

    def test_direct_cost_must_match_agreement_order(self):
        ag = self._agreement()
        other = self._agreement()
        order = self.Order.create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_id': self._contract().id, 'asset_id': self.rented_asset.id,
            'sublet_agreement_id': ag.id})
        with self.assertRaises(ValidationError):
            self.env['gr.sublet.direct.cost'].create({
                'agreement_id': other.id,
                'rental_order_id': order.id,
                'name': 'Wrong operation',
                'amount': 100.0,
            })

    # ---------- exposure flag ----------
    def test_exposure_when_overdue(self):
        # An overdue rent-in started in the past and was due back yesterday;
        # start and end have to be in that order for the period to be real.
        ag = self._agreement(date_start=date.today() - timedelta(days=30),
                             date_end=date.today() - timedelta(days=1))
        ag.action_generate_rent_in_po()  # committed
        ag._compute_exposure()
        self.assertTrue(ag.exposure_flagged)

    def test_no_exposure_when_within_period(self):
        ag = self._agreement(date_end=date.today() + timedelta(days=30))
        ag.action_generate_rent_in_po()
        ag._compute_exposure()
        self.assertFalse(ag.exposure_flagged)

    def test_exposure_clears_on_return(self):
        ag = self._agreement(date_start=date.today() - timedelta(days=30),
                             date_end=date.today() - timedelta(days=1))
        ag.action_generate_rent_in_po()
        ag.action_mark_returned()   # no orders out
        ag._compute_exposure()
        self.assertFalse(ag.exposure_flagged)
        self.assertEqual(ag.state, 'returned')

    # ---------- rent-out link + constraint ----------
    def test_rentout_link(self):
        ag = self._agreement()
        o = self.Order.create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_id': self._contract().id, 'asset_id': self.rented_asset.id,
            'sublet_agreement_id': ag.id})
        self.assertIn(o, ag.rental_order_ids)
        self.assertEqual(ag.rental_order_count, 1)

    def test_rentout_auto_links_active_sublet_agreement(self):
        ag = self._agreement()
        ag.action_generate_rent_in_po()
        order = self.Order.create({
            'partner_id': self.customer.id,
            'site_id': self.site.id,
            'contract_id': self._contract().id,
            'asset_id': self.rented_asset.id,
        })
        self.assertEqual(order.sublet_agreement_id, ag)
        self.assertIn(order, ag.rental_order_ids)

    def test_asset_mismatch_blocked(self):
        ag = self._agreement()  # for rented_asset
        with self.assertRaises(ValidationError):
            self.Order.create({
                'partner_id': self.customer.id, 'site_id': self.site.id,
                'contract_id': self._contract().id,
                'asset_id': self.owned_asset.id,   # mismatch!
                'sublet_agreement_id': ag.id})

    def test_cannot_return_with_unit_out(self):
        ag = self._agreement()
        ag.action_generate_rent_in_po()
        o = self.Order.create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_id': self._contract().id, 'asset_id': self.rented_asset.id,
            'sublet_agreement_id': ag.id,
            'date_requested': fields.Datetime.now(),
            'planned_dispatch_datetime': fields.Datetime.now(),
            'planned_return_datetime': fields.Datetime.now() + timedelta(days=10),
        })
        self._confirm_order(o); o.action_reserve()
        # force an active-out state to simulate the unit still out with a customer
        o.write({'state': 'on_rent'})
        with self.assertRaises(UserError):
            ag.action_mark_returned()

    # ---------- server guards: only third-party units selectable ----------
    def test_agreement_asset_must_be_rented_in(self):
        with self.assertRaises(ValidationError) as caught:
            self._agreement(asset_id=self.owned_asset.id)
        self.assertIn('Third-Party equipment', str(caught.exception))

    def test_agreement_vendor_must_match_asset_supplier(self):
        other_vendor = self.env['res.partner'].create({'name': 'Other Vendor'})
        with self.assertRaises(ValidationError) as caught:
            self._agreement(vendor_id=other_vendor.id)
        self.assertIn('rented from', str(caught.exception))

    # ---------- margin report view exists and is queryable ----------
    def test_margin_report_queryable(self):
        ag = self._agreement()
        self.Order.create({
            'partner_id': self.customer.id, 'site_id': self.site.id,
            'contract_id': self._contract().id, 'asset_id': self.rented_asset.id,
            'sublet_agreement_id': ag.id})
        rows = self.env['gr.sublet.margin.report'].search([])
        # at least our rented-in order shows, tagged rented_in
        self.assertTrue(any(r.owner_type == 'rented_in' for r in rows))

    def test_margin_uses_generated_monthly_customer_billing(self):
        ag = self._agreement(rent_in_amount=500.0)
        order = self._rentout_order(ag, self._monthly_contract())
        self._approved_log(order, 80.0)
        base = fields.Date.context_today(self.env['gr.billing.run'])
        run = self.env['gr.billing.run'].create({
            'date_from': base - timedelta(days=1),
            'date_to': base + timedelta(days=15),
            'rental_order_id': order.id,
        })
        run.action_generate()
        self.assertEqual(run.invoice_ids.amount_untaxed, 1000.0)
        ag._compute_margin()
        self.assertEqual(ag.revenue_out, 1000.0)
        self.assertEqual(ag.cost_in, 500.0)
        self.assertEqual(ag.extra_direct_cost, 0.0)
        self.assertEqual(ag.total_cost, 500.0)
        self.assertEqual(ag.margin, 500.0)

        self.env['gr.sublet.direct.cost'].create({
            'agreement_id': ag.id,
            'rental_order_id': order.id,
            'name': 'Maintenance repair',
            'cost_type': 'maintenance',
            'amount': 100.0,
        })
        ag._compute_margin()
        self.assertEqual(ag.revenue_out, 1000.0)
        self.assertEqual(ag.cost_in, 500.0)
        self.assertEqual(ag.extra_direct_cost, 100.0)
        self.assertEqual(ag.total_cost, 600.0)
        self.assertEqual(ag.margin, 400.0)

        self.env.flush_all()
        rows = self.env['gr.sublet.margin.report'].search([
            ('order_id', '=', order.id)
        ])
        self.assertEqual(rows.revenue_out, 1000.0)
        self.assertEqual(rows.cost_in, 500.0)
        self.assertEqual(rows.extra_direct_cost, 100.0)
        self.assertEqual(rows.total_cost, 600.0)
        self.assertEqual(rows.margin, 400.0)

    def test_auto_linked_monthly_sublet_margin_25000(self):
        ag = self._agreement(rent_in_amount=20000.0)
        ag.action_generate_rent_in_po()
        order = self._rentout_order(
            ag, self._monthly_contract(base_monthly_rate=25000.0),
            explicit_sublet=False)
        self.assertEqual(order.sublet_agreement_id, ag)
        self._approved_log(order, 80.0)
        base = fields.Date.context_today(self.env['gr.billing.run'])
        run = self.env['gr.billing.run'].create({
            'date_from': base - timedelta(days=1),
            'date_to': base + timedelta(days=15),
            'rental_order_id': order.id,
        })
        run.action_generate()
        self.assertEqual(run.invoice_ids.amount_untaxed, 25000.0)

        ag._compute_rentout()
        ag._compute_margin()
        self.assertEqual(ag.rental_order_count, 1)
        self.assertEqual(ag.revenue_out, 25000.0)
        self.assertEqual(ag.cost_in, 20000.0)
        self.assertEqual(ag.margin, 5000.0)

        self.env.flush_all()
        rows = self.env['gr.sublet.margin.report'].search([
            ('order_id', '=', order.id)
        ])
        self.assertEqual(rows.revenue_out, 25000.0)
        self.assertEqual(rows.cost_in, 20000.0)
        self.assertEqual(rows.margin, 5000.0)
