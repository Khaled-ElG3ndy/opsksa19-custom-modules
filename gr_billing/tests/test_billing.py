# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestBilling(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Run = cls.env['gr.billing.run']
        cls.Log = cls.env['gr.hour.log']
        cls.partner = cls.env['res.partner'].create({'name': 'Bill Customer'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Bill Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Bill GM', 'login': 'bill_gm', 'email': 'bill_gm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})
        # Ensure a 15% sale tax exists (the post-init hook normally creates it;
        # create one here for a clean test DB if missing).
        Tax = cls.env['account.tax']
        existing = Tax.search([
            ('type_tax_use', '=', 'sale'), ('amount_type', '=', 'percent'),
            ('amount', '=', 15.0),
            ('company_id', '=', cls.env.company.id)], limit=1)
        cls.tax = existing or Tax.create({
            'name': 'VAT 15% (Sales)', 'amount': 15.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': cls.env.company.id})

    def _contract(self, included=8.0, mx=12.0, **kw):
        vals = {
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': included, 'max_hours_per_day': mx,
            'base_daily_rate': 1000.0, 'overtime_hour_rate': 50.0,
            'violation_hour_rate': 120.0, 'standby_rate': 0.0}
        vals.update(kw)
        c = self.env['gr.rental.contract'].create(vals)
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _order(self, contract, start_meter=0.0):
        code = self.env['ir.sequence'].next_by_code(
            'gr.generator.asset') or 'BILL-GEN'
        a = self.env['gr.generator.asset'].create({
            'name': 'Bill Gen',
            'code': code,
            'serial_number': '%s-SN' % code.replace('/', '-'),
            'pm_interval_hours': 2000.0,
            'current_hour_meter': start_meter,
        })
        o = self.env['gr.rental.order'].create({
            'partner_id': self.partner.id, 'site_id': self.site.id,
            'contract_id': contract.id, 'asset_id': a.id})
        o.action_confirm(); o.action_reserve()
        if 'gr.rental.inspection' in self.env:
            insp = self.env['gr.rental.inspection'].create({
                'rental_order_id': o.id, 'mode': 'delivery'})
            insp._populate_default_checklist(); insp.action_pass()
        o.action_dispatch()
        o.start_meter_reading = start_meter
        o.action_install(); o.action_start_rental()
        return o

    def _confirmed_order(self, contract):
        code = self.env['ir.sequence'].next_by_code(
            'gr.generator.asset') or 'BILL-CONF-GEN-1'
        a = self.env['gr.generator.asset'].create({
            'name': 'Bill Confirmed Gen',
            'code': code,
            'serial_number': 'BILL-SN-1',
            'specification': '500 kVA',
            'pm_interval_hours': 2000.0,
            'rental_daily_rate': 100.0,
        })
        o = self.env['gr.rental.order'].create({
            'partner_id': self.partner.id,
            'site_id': self.site.id,
            'contract_id': contract.id,
            'asset_id': a.id,
        })
        o.action_confirm()
        return o

    def _approved_log(self, order, current, prev_meter=0.0, day_offset=1, span=1):
        base = fields.Date.context_today(self.Log)
        log = self.Log.create({
            'rental_order_id': order.id,
            'current_meter_reading': current,
            'reading_date': base + timedelta(days=day_offset),
            'previous_meter_reading': prev_meter,
            'previous_reading_date': base + timedelta(days=day_offset - span),
        })
        log.action_submit()
        log.with_user(self.gm).action_approve()
        return log

    def _run(self, **kw):
        base = fields.Date.context_today(self.Run)
        vals = {'date_from': base - timedelta(days=5),
                'date_to': base + timedelta(days=10),
                'partner_id': self.partner.id}
        vals.update(kw)
        return self.Run.create(vals)

    # ---------- generation ----------
    def test_generate_creates_draft_invoice(self):
        c = self._contract()
        o = self._order(c)
        self._approved_log(o, 10.0)  # 10h: 8 reg + 2 ot
        run = self._run()
        run.action_generate()
        self.assertEqual(run.state, 'done')
        self.assertEqual(len(run.invoice_ids), 1)
        inv = run.invoice_ids
        self.assertEqual(inv.move_type, 'out_invoice')
        self.assertEqual(inv.state, 'draft')
        self.assertEqual(inv.partner_id, self.partner)
        self.assertEqual(inv.rental_order_id, o)
        self.assertIn(inv, o.invoice_ids)
        self.assertEqual(o.invoice_count, 1)

    def test_invoice_has_itemized_lines_and_vat(self):
        c = self._contract()
        o = self._order(c)
        self._approved_log(o, 15.0)  # 8 reg + 4 ot + 3 violation
        run = self._run()
        run.action_generate()
        inv = run.invoice_ids
        billable_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type not in ('line_note', 'line_section'))
        note_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type == 'line_note')
        labels = billable_lines.mapped('name')
        self.assertTrue(any('Base Daily' in l for l in labels))
        self.assertTrue(any('Overtime' in l for l in labels))
        self.assertTrue(any('Violation' in l for l in labels))
        self.assertFalse(note_lines)
        # every line carries the 15% tax
        for line in billable_lines:
            self.assertIn(self.tax, line.tax_ids)
            self.assertIn(o.asset_id.display_name, line.name)
            self.assertIn(o.asset_id.code, line.name)
            self.assertIn(o.asset_id.serial_number, line.name)
            self.assertIn(o.asset_id.code, line.rental_equipment_reference)
            self.assertIn(
                o.asset_id.serial_number, line.rental_equipment_reference)

    def test_monthly_contract_bills_fixed_amount_not_usage_hours(self):
        c = self._contract(
            contract_type='monthly_with_included_hours',
            base_daily_rate=0.0,
            base_monthly_rate=1000.0,
            hourly_rate=0.0,
            overtime_hour_rate=0.0,
            violation_hour_rate=0.0,
            included_hours_per_day=8.0,
            max_hours_per_day=0.0,
        )
        o = self._order(c)
        self._approved_log(o, 80.0, day_offset=10, span=10)
        run = self._run()
        run.action_generate()
        inv = run.invoice_ids
        billable_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type not in ('line_note', 'line_section'))
        self.assertEqual(len(billable_lines), 1)
        line = billable_lines
        self.assertIn('Monthly Rental', line.name)
        self.assertIn(o.asset_id.display_name, line.name)
        self.assertEqual(line.quantity, 1.0)
        self.assertEqual(line.price_unit, 1000.0)
        self.assertEqual(inv.amount_untaxed, 1000.0)

    def test_hourly_contract_bills_usage_hours(self):
        c = self._contract(
            contract_type='hourly',
            base_daily_rate=0.0,
            included_hours_per_day=0.0,
            max_hours_per_day=0.0,
            hourly_rate=10.0,
            overtime_hour_rate=0.0,
            violation_hour_rate=0.0,
        )
        o = self._order(c)
        self._approved_log(o, 80.0, day_offset=10, span=10)
        run = self._run()
        run.action_generate()
        inv = run.invoice_ids
        billable_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type not in ('line_note', 'line_section'))
        self.assertEqual(len(billable_lines), 1)
        line = billable_lines
        self.assertIn('Hourly Rental', line.name)
        self.assertEqual(line.quantity, 80.0)
        self.assertEqual(line.price_unit, 10.0)

    # ---------- billed-once integrity ----------
    def test_log_billed_once(self):
        c = self._contract()
        o = self._order(c)
        log = self._approved_log(o, 10.0)
        run = self._run()
        run.action_generate()
        self.assertTrue(log.billed)
        self.assertTrue(log.invoice_id)
        # a second run over the same range finds nothing billable
        run2 = self._run()
        with self.assertRaises(UserError):
            run2.action_generate()

    def test_no_logs_raises(self):
        run = self._run()
        with self.assertRaises(UserError):
            run.action_generate()

    # ---------- per-order grouping ----------
    def test_per_order_grouping(self):
        c = self._contract()
        o1 = self._order(c)
        o2 = self._order(c)
        self._approved_log(o1, 10.0)
        self._approved_log(o2, 9.0)
        run = self._run()
        run.action_generate()
        # two orders -> two invoices
        self.assertEqual(len(run.invoice_ids), 2)

    # ---------- cancel / release ----------
    def test_cancel_releases_logs(self):
        c = self._contract()
        o = self._order(c)
        log = self._approved_log(o, 10.0)
        run = self._run()
        run.action_generate()
        self.assertTrue(log.billed)
        run.action_cancel()
        self.assertEqual(run.state, 'cancelled')
        self.assertFalse(log.billed)
        self.assertFalse(log.invoice_id)

    def test_cannot_cancel_when_posted(self):
        c = self._contract()
        o = self._order(c)
        self._approved_log(o, 10.0)
        run = self._run()
        run.action_generate()
        inv = run.invoice_ids
        inv.action_post()
        with self.assertRaises(UserError):
            run.action_cancel()

    # ---------- date guard ----------
    def test_date_order_guard(self):
        base = fields.Date.context_today(self.Run)
        with self.assertRaises(UserError):
            self.Run.create({'date_from': base, 'date_to': base - timedelta(days=3)})

    # ---------- sequence ----------
    def test_sequence_generation(self):
        run = self._run()
        self.assertTrue(run.name.startswith('GR/BILL/'))

    # ---------- filter by order ----------
    def test_order_filter(self):
        c = self._contract()
        o1 = self._order(c)
        o2 = self._order(c)
        self._approved_log(o1, 10.0)
        self._approved_log(o2, 9.0)
        run = self._run(rental_order_id=o1.id)
        run.action_generate()
        self.assertEqual(len(run.invoice_ids), 1)
        self.assertEqual(run.invoice_ids.invoice_origin, o1.name)

    def test_rental_order_create_invoice_button(self):
        c = self._contract()
        o = self._order(c)
        log = self._approved_log(o, 10.0)
        action = o.action_create_invoice()
        inv = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(inv.rental_order_id, o)
        self.assertEqual(log.invoice_id, inv)
        self.assertEqual(inv.invoice_origin, o.name)
        self.assertEqual(o.invoice_count, 1)

    def test_confirmed_rental_order_prefills_invoice_from_rented_serials(self):
        c = self._contract()
        o = self._confirmed_order(c)
        generic_asset_product = self.env['product.product'].create({
            'name': 'Generic Rental Product',
        })
        generic_contract_product = self.env['product.product'].create({
            'name': 'Generic Contract Product',
        })
        o.item_line_ids[0].equipment_asset_id.product_id = generic_asset_product
        self.env['gr.rental.contract.line'].create({
            'contract_id': c.id,
            'product_id': generic_contract_product.id,
        })
        extra = self.env['gr.generator.asset'].create({
            'name': 'Bill Confirmed Gen Extra',
            'code': 'BILL-CONF-GEN-2',
            'serial_number': 'BILL-SN-2',
            'specification': 'Second generator',
            'pm_interval_hours': 2000.0,
            'rental_daily_rate': 175.0,
            'owner_type': 'rented_in',
            'owner_partner_id': self.env['res.partner'].create({
                'name': 'Rental Supplier',
            }).id,
            'supplier_equipment_ref': 'SUP-GEN-2',
        })
        extra_line = self.env['gr.rental.order.line'].create({
            'order_id': o.id,
            'equipment_asset_id': extra.id,
            'quantity_days': 3.0,
        })
        action = o.action_create_invoice()
        inv = self.env['account.move'].browse(action['res_id'])
        note_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type == 'line_note')
        billable_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type not in ('line_note', 'line_section'))
        self.assertEqual(inv.state, 'draft')
        self.assertEqual(inv.move_type, 'out_invoice')
        self.assertEqual(inv.partner_id, self.partner)
        self.assertEqual(inv.rental_order_id, o)
        self.assertEqual(inv.invoice_origin, o.name)
        self.assertFalse(note_lines)
        self.assertEqual(len(billable_lines), len(o.item_line_ids))
        self.assertFalse(billable_lines.mapped('product_id'))
        for order_line in o.item_line_ids:
            matching_lines = billable_lines.filtered(
                lambda line: order_line.equipment_asset_id.display_name in line.name)
            self.assertTrue(matching_lines)
            self.assertEqual(
                matching_lines[0].rental_asset_type,
                order_line.asset_type_display_name)
            self.assertIn(
                order_line.equipment_asset_id.code, matching_lines[0].name)
            self.assertIn(
                order_line.asset_serial_number, matching_lines[0].name)
            self.assertIn(
                order_line.equipment_asset_id.code,
                matching_lines[0].rental_equipment_reference)
            self.assertIn(
                order_line.asset_serial_number,
                matching_lines[0].rental_equipment_reference)
            self.assertFalse(any(
                'Type:' in line.name or 'النوع:' in line.name
                for line in matching_lines))
            self.assertTrue(any(
                order_line.equipment_asset_id.display_name in line.name
                for line in billable_lines))
            self.assertTrue(any(
                order_line.asset_serial_number in line.name
                for line in billable_lines))
        self.assertFalse(any(
            generic_asset_product.display_name in line.name
            or generic_contract_product.display_name in line.name
            for line in billable_lines))
        extra_invoice_line = billable_lines.filtered(
            lambda line: extra.display_name in line.name)
        self.assertEqual(len(extra_invoice_line), 1)
        self.assertIn(extra.supplier_equipment_ref, extra_invoice_line.name)
        self.assertIn(
            extra.supplier_equipment_ref,
            extra_invoice_line.rental_equipment_reference)
        self.assertEqual(extra_invoice_line.quantity, extra_line.quantity_days)
        self.assertEqual(extra_invoice_line.price_unit, extra_line.daily_rate)
        self.assertIn(inv, o.invoice_ids)
        self.assertEqual(o.invoice_count, 1)

    def test_create_invoice_reuses_existing_draft_invoice(self):
        c = self._contract()
        o = self._confirmed_order(c)
        blank = self.env['account.move'].with_context(
            default_move_type='out_invoice').create({
                'move_type': 'out_invoice',
                'partner_id': self.partner.id,
                'currency_id': self.env.company.currency_id.id,
                'invoice_origin': o.name,
                'rental_order_id': o.id,
                'company_id': self.env.company.id,
                'narration': 'Old empty invoice',
            })
        action = o.action_create_invoice()
        inv = self.env['account.move'].browse(action['res_id'])
        billable_lines = inv.invoice_line_ids.filtered(
            lambda line: line.display_type not in ('line_note', 'line_section'))
        self.assertEqual(inv, blank)
        self.assertTrue(billable_lines)
        self.assertIn(o.item_line_ids[0].equipment_asset_id.display_name,
                      billable_lines[0].name)
        self.assertEqual(o.invoice_count, 1)
        second_action = o.action_create_invoice()
        second_inv = self.env['account.move'].browse(second_action['res_id'])
        second_note_lines = second_inv.invoice_line_ids.filtered(
            lambda line: line.display_type == 'line_note')
        self.assertEqual(second_inv, blank)
        self.assertFalse(second_note_lines)
        self.assertEqual(o.invoice_count, 1)
