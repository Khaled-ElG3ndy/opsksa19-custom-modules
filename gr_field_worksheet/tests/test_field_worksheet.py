# -*- coding: utf-8 -*-
import base64
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tests import tagged

# A signature is just captured binary data; the verification logic checks that
# something is present, not that it's a valid image. Use plain bytes that never
# trigger image postprocessing.
_SIG = base64.b64encode(b'signature-data-captured-on-tablet')


@tagged('post_install', '-at_install')
class TestFieldWorksheet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.WS = cls.env['gr.field.worksheet']
        cls.Asset = cls.env['gr.generator.asset']
        cls.Job = cls.env['gr.maintenance.job']
        cls.customer = cls.env['res.partner'].create({'name': 'WS Customer'})
        cls.asset = cls.Asset.create({
            'name': 'WS Gen', 'pm_interval_hours': 2000.0,
            'serial_number': 'SN-WS-001'})
        cls.gm = cls.env['res.users'].create({
            'name': 'WS GM', 'login': 'ws_gm', 'email': 'wsgm@example.com',
            'group_ids': [
                (4, cls.env.ref('base.group_user').id),
                (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
            ]})

    def _ws(self, **kw):
        vals = {'asset_id': self.asset.id, 'partner_id': self.customer.id}
        vals.update(kw)
        return self.WS.create(vals)

    # ---------- sequence + checklist ----------
    def test_sequence_generation(self):
        w = self._ws()
        self.assertTrue(w.name.startswith('GR/FSR/'))

    def test_checklist_master_seeded(self):
        items = self.env['gr.field.worksheet.check.item'].search([])
        self.assertGreaterEqual(len(items), 28)
        self.assertIn('Engine oil level and condition', items.mapped('name'))

    def test_populate_checklist(self):
        w = self._ws()
        w._populate_default_checklist()
        self.assertGreaterEqual(len(w.checklist_ids), 28)

    def test_create_auto_populates_checklist(self):
        w = self._ws()
        self.assertGreaterEqual(len(w.checklist_ids), 28)

    # ---------- serial scan matching ----------
    def test_serial_scan_match(self):
        w = self._ws(scanned_serial='SN-WS-001')
        self.assertTrue(w.serial_scan_ok)

    def test_serial_scan_mismatch(self):
        w = self._ws(scanned_serial='WRONG-SERIAL')
        self.assertFalse(w.serial_scan_ok)

    def test_serial_scan_case_insensitive(self):
        w = self._ws(scanned_serial='  sn-ws-001 ')
        self.assertTrue(w.serial_scan_ok)

    # ---------- verification gate (the core safety) ----------
    def test_verify_blocked_without_signature(self):
        w = self._ws(scanned_serial='SN-WS-001')
        w.action_submit()
        with self.assertRaises(UserError):
            w.action_verify()  # no technician signature

    def test_verify_blocked_without_customer_proof(self):
        # require customer signature (default True) but none provided
        w = self._ws(scanned_serial='SN-WS-001',
                     technician_signature=_SIG)
        w.action_submit()
        with self.assertRaises(UserError):
            w.action_verify()

    def test_verify_blocked_on_serial_mismatch(self):
        w = self._ws(scanned_serial='WRONG',
                     technician_signature=_SIG,
                     customer_signature=_SIG)
        w.action_submit()
        with self.assertRaises(UserError):
            w.action_verify()  # serial scan required + mismatched

    def test_verify_succeeds_with_full_bundle(self):
        w = self._ws(scanned_serial='SN-WS-001',
                     technician_signature=_SIG,
                     customer_signature=_SIG,
                     customer_ack_name='Customer Rep')
        w.action_submit()
        w.action_verify()
        self.assertTrue(w.verified)
        self.assertEqual(w.state, 'verified')
        self.assertTrue(w.verified_on)
        self.assertEqual(w.verified_by_id, self.env.user)

    def test_pin_substitutes_when_customer_sig_not_required(self):
        w = self._ws(scanned_serial='SN-WS-001',
                     technician_signature=_SIG,
                     verification_pin='4821',
                     require_customer_signature=False)
        w.action_submit()
        w.action_verify()
        self.assertTrue(w.verified)

    def test_gps_required_blocks(self):
        w = self._ws(scanned_serial='SN-WS-001',
                     technician_signature=_SIG, customer_signature=_SIG,
                     require_gps=True)
        w.action_submit()
        with self.assertRaises(UserError):
            w.action_verify()  # gps required, none given
        w.write({'gps_latitude': 21.4858, 'gps_longitude': 39.1925})
        w.action_verify()
        self.assertTrue(w.verified)

    # ---------- integrity of a verified worksheet ----------
    def test_verified_cannot_cancel(self):
        w = self._ws(scanned_serial='SN-WS-001',
                     technician_signature=_SIG, customer_signature=_SIG)
        w.action_submit(); w.action_verify()
        with self.assertRaises(UserError):
            w.action_cancel()

    def test_verified_cannot_reset(self):
        w = self._ws(scanned_serial='SN-WS-001',
                     technician_signature=_SIG, customer_signature=_SIG)
        w.action_submit(); w.action_verify()
        with self.assertRaises(UserError):
            w.action_reset_draft()

    # ---------- link rules ----------
    def test_link_from_job_sets_asset(self):
        job = self.Job.create({'asset_id': self.asset.id, 'job_type': 'preventive'})
        w = self.WS.new({'job_id': job.id})
        w._onchange_job()
        self.assertEqual(w.asset_id, self.asset)

    def test_job_button_creates_linked_worksheet(self):
        self.asset.write({
            'owner_type': 'customer_owned',
            'owner_partner_id': self.customer.id,
            'current_hour_meter': 42.0,
        })
        job = self.Job.create({
            'asset_id': self.asset.id,
            'job_type': 'preventive',
            'technician_id': self.env.user.id,
        })
        action = job.action_create_field_worksheet()
        worksheet = self.WS.browse(action['res_id'])
        self.assertEqual(worksheet.job_id, job)
        self.assertEqual(worksheet.asset_id, self.asset)
        self.assertEqual(worksheet.partner_id, self.customer)
        self.assertEqual(worksheet.hour_reading, 42.0)
        self.assertGreaterEqual(len(worksheet.checklist_ids), 28)
        self.assertEqual(job.field_worksheet_count, 1)

        view_action = job.action_view_field_worksheets()
        self.assertEqual(view_action['res_id'], worksheet.id)

    def test_cannot_link_both(self):
        job = self.Job.create({'asset_id': self.asset.id, 'job_type': 'preventive'})
        insp = self._make_inspection()
        w = self._ws()
        with self.assertRaises(UserError):
            w.write({'job_id': job.id, 'inspection_id': insp.id})

    def _make_inspection(self):
        partner = self.env['res.partner'].create({'name': 'Insp Cust WS'})
        site = self.env['gr.customer.site'].create({
            'name': 'WS Insp Site', 'partner_id': partner.id})
        c = self.env['gr.rental.contract'].create({
            'partner_id': partner.id, 'site_id': site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0})
        c.action_submit()
        c.with_user(self.gm).action_approve()
        c.action_activate()
        o = self.env['gr.rental.order'].create({
            'partner_id': partner.id, 'site_id': site.id,
            'contract_id': c.id, 'asset_id': self.asset.id})
        return self.env['gr.rental.inspection'].create({
            'rental_order_id': o.id, 'mode': 'delivery'})
