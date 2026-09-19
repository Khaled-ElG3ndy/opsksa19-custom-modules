# -*- coding: utf-8 -*-
import base64
from io import BytesIO
from datetime import timedelta
from unittest.mock import patch
from lxml import etree
from pypdf import PdfReader
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tests import tagged

_SIG = base64.b64encode(b'customer-signature-data')


@tagged('post_install', '-at_install')
class TestCustomerApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('ar_001')
        # Filenames and report labels now come from i18n/ar.po. Activating a
        # language does not backfill catalogues for modules installed before
        # it, so the module is retranslated explicitly.
        cls.env['ir.module.module'].search([
            ('name', '=', 'gr_customer_approval'), ('state', '=', 'installed'),
        ])._update_translations(['ar_001'])
        cls.Order = cls.env['gr.rental.order']
        cls.Asset = cls.env['gr.generator.asset']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Approval Cust', 'email': 'cust@example.com',
            'phone': '+966500000000'})
        cls.no_contact = cls.env['res.partner'].create({'name': 'No Contact Cust'})
        cls.site = cls.env['gr.customer.site'].create({
            'name': 'Appr Site', 'partner_id': cls.partner.id})
        cls.gm = cls.env['res.users'].create({
            'name': 'Appr GM', 'login': 'appr_gm', 'email': 'agm@example.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id),
                          (4, cls.env.ref('gr_security_base.group_generator_general_manager').id),
                          (4, cls.env.ref('gr_security_base.group_generator_operations_officer').id)]})

    def _contract(self, partner=None, **overrides):
        p = partner or self.partner
        values = {
            'partner_id': p.id, 'site_id': self.site.id,
            'contract_type': 'daily_with_included_hours',
            'included_hours_per_day': 8.0, 'max_hours_per_day': 12.0,
            'base_daily_rate': 500.0,
        }
        values.update(overrides)
        c = self.env['gr.rental.contract'].create(values)
        c.action_submit(); c.with_user(self.gm).action_approve(); c.action_activate()
        return c

    def _order(self, partner=None, contract=None, **overrides):
        p = partner or self.partner
        a = self.Asset.create({'name': 'Appr Gen', 'pm_interval_hours': 2000.0})
        values = {
            'partner_id': p.id, 'site_id': self.site.id,
            'contract_id': (contract or self._contract(p)).id,
            'asset_id': a.id,
        }
        values.update(overrides)
        return self.Order.create(values)

    def _send_otp_and_capture_code(self, record):
        captured = {}

        def fake_send(rec, code, destination):
            captured['code'] = code
            captured['destination'] = destination
            return True

        with patch.object(type(record), '_render_approval_pdf', return_value=b'%PDF-test'):
            with patch.object(type(record), '_send_otp_via_channel', fake_send):
                record.action_send_otp()
        return captured['code'], captured['destination']

    def _prepare_approval_copy(self, record, lang='en_US'):
        with patch.object(type(record), '_render_approval_pdf', return_value=b'%PDF-test'):
            return record._generate_approval_copy(language=lang)

    def _approve_with_signature(self, record, name='Mr Customer'):
        with patch.object(type(record), '_render_approval_pdf', return_value=b'%PDF-test'):
            if not record.current_approval_document_id:
                record._generate_approval_copy(language='en_US')
            record.approval_signature = _SIG
            record.approval_signed_by = name
            record.action_approve_by_signature()

    # ---------- the mixin is applied to all target documents ----------
    # These prove approval_partner_id is POPULATED on create (the v1 bug).
    def test_mixin_on_rental_order(self):
        o = self._order()
        self.assertEqual(o.approval_state, 'pending')
        self.assertEqual(o.approval_partner_id, self.partner,
                         "approval_partner_id must be populated on create")

    def test_mixin_on_worksheet(self):
        a = self.Asset.create({'name': 'WS Appr Gen', 'pm_interval_hours': 2000.0})
        w = self.env['gr.field.worksheet'].create({
            'asset_id': a.id, 'partner_id': self.partner.id})
        self.assertEqual(w.approval_state, 'pending')
        self.assertEqual(w.approval_partner_id, self.partner,
                         "approval_partner_id must be populated on create")

    def test_mixin_on_rental_inspection(self):
        """The delivery/return note — the third target model."""
        o = self._order()
        insp = self.env['gr.rental.inspection'].create({
            'rental_order_id': o.id, 'mode': 'delivery'})
        self.assertEqual(insp.approval_state, 'pending')
        self.assertEqual(insp.approval_partner_id, self.partner,
                         "approval_partner_id must be populated on create")

    def test_resolver_fallback_when_field_blank(self):
        """Even if the stored field is cleared, the resolver still finds the
        customer from the document itself."""
        o = self._order()
        o.approval_partner_id = False
        self.assertEqual(o._resolve_approval_partner(), self.partner)

    def test_rental_order_approval_buttons_are_visible_view_controls(self):
        base_view = self.env.ref('gr_rental_order.view_gr_rental_order_form')
        combined = self.env['gr.rental.order'].get_view(
            view_id=base_view.id, view_type='form')['arch']
        arch = etree.fromstring(combined.encode())
        page = arch.xpath("//page[@name='customer_approval']")[0]
        required = {
            'action_generate_approval_copy', 'action_preview_document',
            'action_download_pdf', 'action_send_document_to_customer',
            'action_view_approval_copy', 'action_view_approved_document',
            'action_download_approved_document',
        }
        for action in required:
            buttons = page.xpath(".//button[@name='%s']" % action)
            self.assertTrue(buttons, '%s must be available on the approval tab' % action)
            self.assertFalse(
                buttons[0].xpath('ancestor::footer'),
                '%s must not be hidden in a form footer' % action)

        header_generate = arch.xpath(
            "//header/button[@name='action_generate_approval_copy']")
        self.assertTrue(header_generate)
        confirm = arch.xpath("//header/button[@name='action_confirm']")[0]
        self.assertIn("approval_state != 'approved'", confirm.get('invisible', ''))

    def _assert_approval_tab_controls(self, model_name, base_view_xmlid):
        base_view = self.env.ref(base_view_xmlid)
        combined = self.env[model_name].with_user(self.gm).get_view(
            view_id=base_view.id, view_type='form')['arch']
        arch = etree.fromstring(combined.encode())
        pages = arch.xpath("//page[@name='customer_approval']")
        self.assertTrue(pages, '%s must have a Customer Approval tab' % model_name)
        required = {
            'action_generate_approval_copy', 'action_preview_document',
            'action_download_pdf', 'action_send_document_to_customer',
            'action_view_approval_copy', 'action_view_approved_document',
            'action_download_approved_document', 'action_create_new_revision',
        }
        for action in required:
            buttons = pages[0].xpath(".//button[@name='%s']" % action)
            self.assertTrue(
                buttons, '%s must be available on the %s approval tab'
                % (action, model_name))
            self.assertFalse(
                buttons[0].xpath('ancestor::footer'),
                '%s must not be hidden in a form footer' % action)
        self.assertTrue(arch.xpath(
            "//header/button[@name='action_generate_approval_copy']"))
        return arch

    def test_inspection_has_complete_approval_workflow_in_view(self):
        arch = self._assert_approval_tab_controls(
            'gr.rental.inspection',
            'gr_rental_inspection.view_gr_rental_inspection_form')
        pass_button = arch.xpath("//header/button[@name='action_pass']")[0]
        self.assertIn(
            "approval_state != 'approved'", pass_button.get('invisible', ''))

    def test_visit_report_has_complete_approval_workflow_in_view(self):
        arch = self._assert_approval_tab_controls(
            'gr.field.worksheet',
            'gr_field_worksheet.view_gr_field_worksheet_form')
        verify_button = arch.xpath("//header/button[@name='action_verify']")[0]
        self.assertIn(
            "approval_state != 'approved'", verify_button.get('invisible', ''))

    # ---------- 1) sign in person ----------
    def test_approve_by_signature(self):
        o = self._order()
        self._approve_with_signature(o)
        self.assertEqual(o.approval_state, 'approved')
        self.assertEqual(o.approval_method, 'signature')
        self.assertTrue(o.approved_on)
        self.assertTrue(o.current_approval_document_id.approved_attachment_id)

    def test_signature_required_to_approve(self):
        o = self._order()   # no signature captured
        self._prepare_approval_copy(o)
        with self.assertRaises(UserError):
            o.action_approve_by_signature()

    def test_cannot_approve_twice(self):
        o = self._order()
        self._approve_with_signature(o)
        with self.assertRaises(UserError):
            o.action_approve_by_signature()

    # ---------- 2) OTP ----------
    def test_send_otp_email(self):
        o = self._order()
        o.otp_channel = 'email'
        code, destination = self._send_otp_and_capture_code(o)
        self.assertEqual(o.approval_state, 'sent')
        self.assertEqual(destination, 'cust@example.com')
        self.assertEqual(o.otp_sent_to, 'c****@example.com')
        self.assertTrue(o.sudo().otp_code_hash)
        self.assertEqual(len(code), 6)
        self.assertTrue(o.otp_expires_at)

    def test_otp_requires_email(self):
        o = self._order(partner=self.no_contact)
        o.otp_channel = 'email'
        with patch.object(type(o), '_render_approval_pdf', return_value=b'%PDF-test'):
            with self.assertRaises(UserError):
                o.action_send_otp()

    def test_verify_correct_otp_approves(self):
        o = self._order()
        code, _destination = self._send_otp_and_capture_code(o)
        o.otp_input = code
        with patch.object(type(o), '_render_approval_pdf', return_value=b'%PDF-approved'):
            o.action_verify_otp()
        self.assertEqual(o.approval_state, 'approved')
        self.assertEqual(o.approval_method, 'otp')
        self.assertFalse(o.sudo().otp_code_hash)   # hash cleared after use

    def test_wrong_otp_rejected_and_counted(self):
        """A wrong code must NOT approve, and the attempt MUST be counted.

        The counter is the lockout. It is written without raising, because a
        raise would roll the write back and the lockout would never engage."""
        o = self._order()
        self._send_otp_and_capture_code(o)
        o.otp_input = '000000'
        res = o.action_verify_otp()          # returns a warning, does not raise
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get('tag'), 'display_notification')
        self.assertEqual(o.otp_attempts, 1, "failed attempt must persist")
        self.assertEqual(o.approval_state, 'sent')   # still not approved
        self.assertNotEqual(o.approval_state, 'approved')

    def test_attempts_accumulate_to_lockout(self):
        """Five wrong codes must actually lock the document out."""
        o = self._order()
        code, _destination = self._send_otp_and_capture_code(o)
        o.otp_input = '000000'
        for i in range(1, 6):
            o.action_verify_otp()
            self.assertEqual(o.otp_attempts, i)
        # now locked: even the CORRECT code is refused
        o.otp_input = code
        res = o.action_verify_otp()
        self.assertEqual(res.get('tag'), 'display_notification')
        self.assertEqual(o.approval_state, 'sent')   # NOT approved

    def test_otp_locks_after_max_attempts(self):
        o = self._order()
        self._send_otp_and_capture_code(o)
        o.otp_attempts = 5      # already at the limit
        o.otp_input = '000000'
        res = o.action_verify_otp()
        self.assertEqual(res.get('tag'), 'display_notification')
        self.assertEqual(o.approval_state, 'sent')

    def test_expired_otp_rejected(self):
        o = self._order()
        code, _destination = self._send_otp_and_capture_code(o)
        o.otp_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        o.otp_input = code
        res = o.action_verify_otp()          # expired -> warning, not approved
        self.assertEqual(res.get('tag'), 'display_notification')
        self.assertEqual(o.approval_state, 'sent')

    def test_verify_without_sending_blocked(self):
        o = self._order()
        o.otp_input = '123456'
        with self.assertRaises(UserError):
            o.action_verify_otp()

    # ---------- unconnected channels fail clearly (not silently) ----------
    def test_whatsapp_channel_not_connected_yet(self):
        o = self._order()
        o.otp_channel = 'whatsapp'
        with patch.object(type(o), '_render_approval_pdf', return_value=b'%PDF-test'):
            with self.assertRaises(UserError):
                o.action_send_otp()   # clear message until a provider is connected
        self.assertEqual(o.approval_state, 'pending')
        self.assertFalse(o.sudo().otp_code_hash)

    # ---------- withdraw ----------
    def test_reset_approval(self):
        o = self._order()
        self._approve_with_signature(o)
        o.action_reset_approval()
        self.assertEqual(o.approval_state, 'pending')
        self.assertFalse(o.approval_method)
        self.assertFalse(o.approved_on)

    def test_approval_fields_locked_after_approval(self):
        o = self._order()
        self._approve_with_signature(o)
        with self.assertRaises(UserError):
            o.approval_signature = _SIG

    def test_confirm_requires_customer_approval(self):
        o = self._order()
        with self.assertRaises(UserError):
            o.action_confirm()
        self._approve_with_signature(o)
        o.action_confirm()
        self.assertEqual(o.state, 'confirmed')

    def test_delivery_inspection_pass_requires_customer_approval(self):
        o = self._order()
        insp = self.env['gr.rental.inspection'].create({
            'rental_order_id': o.id, 'mode': 'delivery'})
        insp._populate_default_checklist()
        with self.assertRaises(UserError):
            insp.action_pass()
        self._approve_with_signature(insp)
        insp.action_pass()
        self.assertEqual(insp.state, 'passed')

    def test_return_inspection_pass_requires_customer_approval(self):
        order = self._order()
        inspection = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'return'})
        inspection._populate_default_checklist()
        with self.assertRaises(UserError):
            inspection.action_pass()
        self._approve_with_signature(inspection)
        inspection.action_pass()
        self.assertEqual(inspection.state, 'passed')

    def test_worksheet_verify_requires_customer_approval(self):
        a = self.Asset.create({'name': 'WS Gate Gen', 'pm_interval_hours': 2000.0})
        w = self.env['gr.field.worksheet'].create({
            'asset_id': a.id,
            'partner_id': self.partner.id,
            'technician_signature': _SIG,
            'customer_signature': _SIG,
            'verification_pin': '1234',
            'require_serial_scan': False,
        })
        w.action_submit()
        with self.assertRaises(UserError):
            w.action_verify()
        self._approve_with_signature(w)
        w.action_verify()
        self.assertEqual(w.state, 'verified')

    def test_approval_log_records_events(self):
        o = self._order()
        self._send_otp_and_capture_code(o)
        self.assertEqual(o.approval_log_count, 2)
        action = o.action_view_approval_logs()
        self.assertEqual(action['res_model'], 'gr.customer.approval.log')

    # ---------- immutable PDF versions ----------
    def test_generate_pdf_copy_stores_version_hash_and_language(self):
        o = self._order()
        copy = self._prepare_approval_copy(o, lang='ar_001')
        self.assertEqual(copy.version, 1)
        self.assertEqual(copy.language, 'ar_001')
        self.assertEqual(copy.state, 'pending')
        self.assertTrue(copy.attachment_id)
        self.assertTrue(copy.file_hash)
        self.assertTrue(copy.content_hash)
        self.assertEqual(o.current_approval_document_id, copy)

    def test_document_filenames_cover_language_type_state_and_version(self):
        order = self._order()
        order.name = 'GR/RO/01614'
        self.assertEqual(
            order.with_context(lang='ar_001')._approval_filename(),
            'عقد_تأجير_GR-RO-01614.pdf')
        self.assertEqual(
            order.with_context(lang='en_US')._approval_filename(),
            'Rental_Agreement_GR-RO-01614.pdf')

        copy = self._prepare_approval_copy(order, lang='ar_001')
        self.assertEqual(
            copy.name, 'نسخة_موافقة_عقد_تأجير_GR-RO-01614.pdf')
        self.assertEqual(copy.attachment_id.name, copy.name)
        self.assertNotIn('/', copy.name)
        self.assertIn('/web/content/%s/' % copy.attachment_id.id,
                      copy.action_view_copy()['url'])

        delivery = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'delivery',
            'name': 'GR/INSP/99488',
        })
        returned = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'return',
            'name': 'GR/INSP/99489',
        })
        worksheet = self.env['gr.field.worksheet'].create({
            'asset_id': order.asset_id.id, 'partner_id': self.partner.id,
            'name': 'GR/VISIT/99125',
        })
        self.assertEqual(
            delivery._approval_filename(lang='en_US'),
            'Delivery_Report_GR-INSP-99488.pdf')
        self.assertEqual(
            returned._approval_filename(lang='ar_001'),
            'محضر_إرجاع_GR-INSP-99489.pdf')
        self.assertEqual(
            worksheet._approval_filename(lang='en_US'),
            'Visit_Report_GR-VISIT-99125.pdf')
        self.assertEqual(
            returned._approval_filename(
                lang='ar_001', approved=True, version=2),
            'محضر_إرجاع_معتمد_GR-INSP-99489_V2.pdf')

    def test_approved_and_second_revision_filenames(self):
        order = self._order()
        order.name = 'GR/RO/01614'
        self._approve_with_signature(order)
        version_one = order.current_approval_document_id
        self.assertEqual(
            version_one.attachment_id.name,
            'Rental_Approval_Copy_GR-RO-01614.pdf')
        self.assertEqual(
            version_one.name,
            'Approved_Rental_Agreement_GR-RO-01614.pdf')
        self.assertEqual(version_one.approved_attachment_id.name, version_one.name)

        with patch.object(type(order), '_render_approval_pdf', return_value=b'%PDF-v2'):
            order.action_create_new_revision()
        version_two = order.current_approval_document_id
        self.assertEqual(version_two.version, 2)
        self.assertEqual(
            version_two.name,
            'Rental_Approval_Copy_GR-RO-01614_V2.pdf')
        self.assertFalse(version_two.name.replace('.pdf', '').isdigit())

    def test_business_change_supersedes_generated_copy(self):
        o = self._order()
        copy = self._prepare_approval_copy(o)
        o.planned_return_datetime = fields.Datetime.now() + timedelta(days=30)
        self.assertEqual(copy.state, 'superseded')
        self.assertFalse(o.current_approval_document_id)
        o.approval_signature = _SIG
        o.approval_signed_by = 'Mr Customer'
        with self.assertRaises(UserError):
            o.action_approve_by_signature()

    def test_approved_pdf_attachment_cannot_be_deleted(self):
        o = self._order()
        self._approve_with_signature(o)
        attachment = o.current_approval_document_id.approved_attachment_id
        with self.assertRaises(UserError):
            attachment.unlink()

    def test_approved_pdf_attachment_allows_access_token_refresh(self):
        o = self._order()
        self._approve_with_signature(o)
        attachment = o.current_approval_document_id.approved_attachment_id.sudo()
        attachment.with_context(approval_document_internal=True).write({
            'access_token': False,
        })
        token = attachment.generate_access_token()[0]
        self.assertTrue(token)
        self.assertEqual(attachment.access_token, token)

    def test_approved_pdf_attachment_content_stays_locked(self):
        o = self._order()
        self._approve_with_signature(o)
        attachment = o.current_approval_document_id.approved_attachment_id.sudo()
        with self.assertRaises(UserError):
            attachment.write({'raw': b'%PDF-tampered'})
        with self.assertRaises(UserError):
            attachment.write({'name': 'tampered.pdf'})

    def test_approved_business_data_is_locked(self):
        o = self._order()
        self._approve_with_signature(o)
        with self.assertRaises(UserError):
            o.planned_return_datetime = fields.Datetime.now() + timedelta(days=10)

    def test_repeated_send_reuses_same_version_and_language(self):
        self.partner.lang = 'ar_001'
        o = self._order()
        copy = self._prepare_approval_copy(o, lang='ar_001')
        template = self.env.ref(
            'gr_customer_approval.mail_template_rental_order_document')
        with patch.object(type(template), 'send_mail', return_value=1) as send_mail:
            o.action_send_document_to_customer()
            o.action_send_document_to_customer()
        self.assertEqual(o.current_approval_document_id, copy)
        self.assertEqual(o.approval_document_count, 1)
        self.assertEqual(copy.sent_count, 2)
        self.assertEqual(send_mail.call_count, 2)
        self.assertIn('الإصدار', o.with_context(lang='ar_001')._approval_document_email_subject())

    def test_arabic_email_and_attachment_link_match_copy_language(self):
        self.partner.lang = 'ar_001'
        o = self._order()
        copy = self._prepare_approval_copy(o, lang='ar_001')
        body = str(o.with_context(lang=copy.language)._approval_document_email_body_html())
        self.assertIn('مرفق', body)
        self.assertIn('الإصدار', body)
        self.assertIn('access_token=', body)
        self.assertNotIn('Attached is', body)

    def test_document_email_is_logged_with_the_exact_pdf(self):
        self.partner.lang = 'ar_001'
        o = self._order()
        copy = self._prepare_approval_copy(o, lang='ar_001')
        Mail = self.env['mail.mail']
        with patch.object(type(Mail), 'send', return_value=True):
            o.action_send_document_to_customer()
        message = self.env['mail.message'].search([
            ('model', '=', o._name), ('res_id', '=', o.id),
            ('message_type', '=', 'email_outgoing'),
        ], order='id desc', limit=1)
        self.assertTrue(message)
        self.assertIn(copy.attachment_id, message.attachment_ids)
        self.assertIn('الإصدار', str(message.body))

    def test_new_revision_keeps_approved_file_and_increments_version(self):
        o = self._order()
        self._approve_with_signature(o)
        old_copy = o.current_approval_document_id
        old_approved_attachment = old_copy.approved_attachment_id
        with patch.object(type(o), '_render_approval_pdf', return_value=b'%PDF-v2'):
            o.action_create_new_revision()
        self.assertEqual(old_copy.state, 'cancelled')
        self.assertEqual(o.current_approval_document_id.version, 2)
        self.assertEqual(o.approval_state, 'pending')
        self.assertTrue(old_approved_attachment.exists())

    # ---------- report language and content ----------
    def _report_html(self, record, lang):
        report = self.env.ref(record._approval_report_xmlid())
        return self.env['ir.actions.report'].with_context(lang=lang)._render_qweb_html(
            report, [record.id])[0].decode()

    def test_four_reports_are_arabic_rtl_or_english_ltr(self):
        order = self._order()
        delivery = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'delivery'})
        returned = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'return'})
        worksheet = self.env['gr.field.worksheet'].create({
            'asset_id': order.asset_id.id, 'partner_id': self.partner.id})
        cases = [
            (order, 'عقد التأجير', 'Rental Agreement'),
            (delivery, 'محضر تسليم الأصل', 'Asset Delivery Report'),
            (returned, 'محضر إرجاع الأصل', 'Asset Return Report'),
            (worksheet, 'تقرير الزيارة الميدانية', 'Field Visit Report'),
        ]
        for record, arabic_title, english_title in cases:
            arabic = self._report_html(record, 'ar_001')
            english = self._report_html(record, 'en_US')
            self.assertIn('dir="rtl"', arabic)
            self.assertIn(arabic_title, arabic)
            self.assertNotIn(english_title, arabic)
            self.assertIn('dir="ltr"', english)
            self.assertIn(english_title, english)
            self.assertNotIn(arabic_title, english)

    def test_monthly_pricing_uses_monthly_rate_not_zero_daily_rate(self):
        contract = self._contract(
            contract_type='monthly_with_included_hours',
            base_daily_rate=0.0,
            base_monthly_rate=20000.0,
            included_hours_per_day=8.0,
            max_hours_per_day=12.0,
            overtime_hour_rate=150.0,
        )
        order = self._order(contract=contract)
        english = self._report_html(order, 'en_US')
        arabic = self._report_html(order, 'ar_001')
        self.assertIn('Base Monthly Rate', english)
        self.assertIn('20,000', english)
        self.assertIn('Included Hours / Day', english)
        self.assertIn('Overtime Hour Rate', english)
        self.assertNotIn('Base Daily Rate', english)
        self.assertIn('20,000', arabic)
        self.assertNotIn('Base Daily Rate', arabic)

    def test_daily_pricing_displays_daily_rate_and_duration(self):
        start = fields.Datetime.now()
        contract = self._contract(base_daily_rate=750.0)
        order = self._order(
            contract=contract,
            planned_install_datetime=start,
            planned_return_datetime=start + timedelta(days=3),
        )
        english = self._report_html(order, 'en_US')
        self.assertIn('Base Daily Rate', english)
        self.assertIn('750.00', english)
        self.assertIn('3 day(s)', english)
        self.assertIn('2,250.00', english)

    def test_old_rental_reports_use_the_unified_layout(self):
        order = self._order()
        cases = [
            (self.env.ref('gr_contract.action_report_gr_rental_contract'),
             order.contract_id),
            (self.env.ref('gr_rental_order.action_report_gr_delivery_note'), order),
            (self.env.ref('gr_rental_order.action_report_gr_install_report'), order),
            (self.env.ref('gr_rental_order.action_report_gr_return_inspection'), order),
        ]
        for report, record in cases:
            html = self.env['ir.actions.report'].with_context(
                lang='en_US')._render_qweb_html(report, [record.id])[0].decode()
            self.assertIn('gr-approval-document', html)
            self.assertIn('gr-doc-header', html)
            self.assertIn('gr-footer', html)

    def test_four_document_types_render_to_pdf_in_both_languages(self):
        order = self._order()
        delivery = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'delivery'})
        returned = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'return'})
        worksheet = self.env['gr.field.worksheet'].create({
            'asset_id': order.asset_id.id, 'partner_id': self.partner.id})
        for record in (order, delivery, worksheet, returned):
            report = self.env.ref(record._approval_report_xmlid())
            for lang in ('ar_001', 'en_US'):
                pdf = self.env['ir.actions.report'].with_context(
                    lang=lang, force_report_rendering=True)._render_qweb_pdf(
                        report, [record.id])[0]
                self.assertTrue(pdf.startswith(b'%PDF'))
                self.assertGreater(len(pdf), 1000)
                self.assertEqual(
                    PdfReader(BytesIO(pdf)).metadata.get('/GRFooterStamped'),
                    'true')

    def test_arabic_pdf_body_keeps_utf8_font_and_hides_default_logo(self):
        order = self._order()
        report = self.env.ref(order._approval_report_xmlid())
        raw_html = self.env['ir.actions.report'].with_context(
            lang='ar_001')._render_qweb_html(report, [order.id])[0]
        html = raw_html.decode()

        self.assertIn('class="article page gr-approval-document"', html)
        self.assertIn('dir="rtl"', html)
        self.assertIn('font-family: GRDataArabic', html)
        self.assertIn('data:font/ttf;base64,', html)
        self.assertNotIn('<img class="gr-logo"', html)

        bodies, _ids, _header, _footer, _args = report.with_context(
            lang='ar_001')._prepare_html(
                raw_html, report_model=order._name)
        wkhtml_body = str(bodies[0])
        self.assertIn('<meta charset="utf-8"', wkhtml_body)
        self.assertIn('عقد التأجير', wkhtml_body)
        self.assertNotIn('Ø¹', wkhtml_body)

    def test_checklist_reference_values_follow_report_language(self):
        order = self._order()
        delivery = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id,
            'mode': 'delivery',
            'checklist_ids': [(0, 0, {
                'name': 'Cabin', 'result': 'fail',
            })],
        })
        worksheet = self.env['gr.field.worksheet'].create({
            'asset_id': order.asset_id.id,
            'partner_id': self.partner.id,
            'checklist_ids': [(0, 0, {
                'name': 'Cabin exterior', 'result': 'ok',
            })],
        })

        delivery_ar = self._report_html(delivery, 'ar_001')
        worksheet_ar = self._report_html(worksheet, 'ar_001')
        delivery_en = self._report_html(delivery, 'en_US')
        worksheet_en = self._report_html(worksheet, 'en_US')

        self.assertIn('الكابينة', delivery_ar)
        self.assertIn('فشل', delivery_ar)
        self.assertNotIn('>Cabin<', delivery_ar)
        self.assertNotIn('>Fail<', delivery_ar)
        self.assertIn('خارج الكابينة', worksheet_ar)
        self.assertIn('موافق', worksheet_ar)
        self.assertNotIn('>Cabin exterior<', worksheet_ar)
        self.assertNotIn('>OK<', worksheet_ar)
        self.assertIn('>Cabin<', delivery_en)
        self.assertIn('>Fail<', delivery_en)
        self.assertIn('>Cabin exterior<', worksheet_en)
        self.assertIn('>OK<', worksheet_en)

    def test_rental_report_contains_generator_and_all_item_lines(self):
        o = self._order()
        item_type = self.env['gr.rental.item.type'].create({
            'name': 'Approval Cable', 'default_daily_rate': 10.0})
        units = self.env['gr.rental.item.unit'].create([
            {'name': 'CABLE-A', 'item_type_id': item_type.id},
            {'name': 'CABLE-B', 'item_type_id': item_type.id},
        ])
        self.env['gr.rental.order.line'].create([
            {'order_id': o.id, 'item_type_id': item_type.id,
             'item_unit_id': units[0].id, 'daily_rate': 10.0},
            {'order_id': o.id, 'item_type_id': item_type.id,
             'item_unit_id': units[1].id, 'daily_rate': 10.0},
        ])
        html = self._report_html(o, 'en_US')
        self.assertIn(o.asset_id.display_name, html)
        self.assertIn('CABLE-A', html)
        self.assertIn('CABLE-B', html)

    def test_delivery_return_and_visit_reports_include_operational_details(self):
        order = self._order()
        item_type = self.env['gr.rental.item.type'].create({
            'name': 'Report Accessory', 'default_daily_rate': 5.0})
        unit = self.env['gr.rental.item.unit'].create({
            'name': 'ACCESSORY-001', 'item_type_id': item_type.id})
        self.env['gr.rental.order.line'].create({
            'order_id': order.id, 'item_type_id': item_type.id,
            'item_unit_id': unit.id, 'daily_rate': 5.0})
        delivery = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'delivery',
            'checklist_ids': [(0, 0, {
                'name': 'Delivery condition', 'result': 'ok',
                'note': 'Delivered clean'})],
        })
        returned = self.env['gr.rental.inspection'].create({
            'rental_order_id': order.id, 'mode': 'return',
            'checklist_ids': [(0, 0, {
                'name': 'Return damage', 'result': 'fail',
                'note': 'Damage observation'})],
        })
        worksheet = self.env['gr.field.worksheet'].create({
            'asset_id': order.asset_id.id, 'partner_id': self.partner.id,
            'remarks': 'Technician recommendation',
            'spare_part_ids': [(0, 0, {
                'part_number': 'PART-001', 'description': 'Oil filter',
                'quantity': 2})],
        })
        delivery_html = self._report_html(delivery, 'en_US')
        return_html = self._report_html(returned, 'en_US')
        visit_html = self._report_html(worksheet, 'en_US')
        self.assertIn('ACCESSORY-001', delivery_html)
        self.assertIn('Delivered clean', delivery_html)
        self.assertIn('Damage observation', return_html)
        self.assertIn('PART-001', visit_html)
        self.assertIn('Technician recommendation', visit_html)
