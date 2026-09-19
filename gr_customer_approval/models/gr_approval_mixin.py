# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from functools import lru_cache
from urllib.parse import quote

from markupsafe import Markup
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError

OTP_LENGTH = 6
OTP_VALID_MINUTES = 15
OTP_MAX_ATTEMPTS = 5
_APPROVAL_LOCKED_FIELDS = {
    'approval_state', 'approval_method', 'approval_partner_id',
    'approval_signature', 'approval_signed_by', 'approval_signed_by_role',
    'approval_notes', 'approved_on', 'approved_by_uid', 'otp_code_hash',
    'otp_salt', 'otp_channel', 'otp_sent_to', 'otp_expires_at',
    'otp_attempts', 'current_approval_document_id',
}


def _hash_otp(code, salt):
    return hashlib.sha256(('%s:%s' % (salt, code)).encode('utf-8')).hexdigest()


def _mask_destination(destination, channel):
    if not destination:
        return ''
    if channel == 'email' and '@' in destination:
        local, domain = destination.rsplit('@', 1)
        return '%s****@%s' % (local[:1], domain)
    clean = ''.join(ch for ch in destination if ch.isdigit() or ch == '+')
    return '****' if len(clean) <= 4 else '****%s' % clean[-4:]


@lru_cache(maxsize=2)
def _approval_font_data_uri(filename):
    path = 'gr_customer_approval/static/src/fonts/%s' % filename
    with tools.file_open(path, 'rb') as font_file:
        encoded = base64.b64encode(font_file.read()).decode('ascii')
    return 'data:font/ttf;base64,%s' % encoded


class GrCustomerApprovalLog(models.Model):
    _name = 'gr.customer.approval.log'
    _description = 'Customer Approval Audit Log'
    _order = 'create_date desc, id desc'

    document_model = fields.Char(string='Document Model', required=True, index=True)
    document_res_id = fields.Integer(string='Document ID', required=True, index=True)
    document_ref = fields.Char(string='Document Reference', required=True)
    partner_id = fields.Many2one('res.partner', string='Customer', index=True)
    approval_document_id = fields.Many2one(
        'gr.customer.approval.document', string='Approval Document',
        ondelete='restrict', index=True)
    event_type = fields.Selection([
        ('generated', 'Approval Copy Generated'),
        ('document_sent', 'Document Sent'),
        ('sent', 'Code Sent'),
        ('failed', 'Failed Verification'),
        ('approved', 'Approved'),
        ('cancelled', 'Approval Cancelled'),
        ('superseded', 'Superseded'),
        ('revision', 'New Revision Created'),
    ], string='Event Type', required=True, index=True)
    approval_method = fields.Selection([
        ('signature', 'Signed in person'),
        ('otp', 'Approved by one-time code'),
    ], string='Approval Method')
    channel = fields.Selection([
        ('email', 'Email'), ('sms', 'SMS'), ('whatsapp', 'WhatsApp'),
    ], string='Channel')
    recipient = fields.Char(string='Recipient')
    attempts = fields.Integer(string='Failed Attempts')
    description = fields.Text(string='Description')
    user_id = fields.Many2one(
        'res.users', string='Responsible User', default=lambda self: self.env.user,
        readonly=True)

    def write(self, vals):
        raise UserError(_('Approval audit log entries cannot be edited.'))

    def unlink(self):
        raise UserError(_('Approval audit log entries cannot be deleted.'))


class GrDocumentReportHelper(models.AbstractModel):
    _name = 'gr.document.report.helper'
    _description = 'Generator Document Report Helper'

    def _approval_is_rtl(self):
        # Layout follows the active language's own direction, so any RTL
        # language added later lays out correctly without a code change.
        code = self.env.context.get('lang') or self.env.lang or ''
        return self.env['res.lang']._get_data(code=code).direction == 'rtl'

    def _approval_arabic_font_css(self):
        self.ensure_one()
        regular = _approval_font_data_uri('NotoSansArabic-Regular.ttf')
        bold = _approval_font_data_uri('NotoSansArabic-Bold.ttf')
        return Markup("""
            @font-face {
                font-family: GRDataArabic;
                src: url('%s') format('truetype');
                font-style: normal;
                font-weight: 400;
            }
            @font-face {
                font-family: GRDataArabic;
                src: url('%s') format('truetype');
                font-style: normal;
                font-weight: 700;
            }
        """) % (regular, bold)

    def _document_filename_reference(self, reference=None):
        self.ensure_one()
        reference = reference or self.display_name or str(self.id)
        reference = re.sub(r'[/\\]+', '-', reference.strip())
        reference = re.sub(r'[^\w.-]+', '-', reference, flags=re.UNICODE)
        return re.sub(r'-{2,}', '-', reference).strip('._-') or str(self.id)

    def _approval_format_amount(self, amount, currency=None):
        self.ensure_one()
        currency = currency or self.company_id.currency_id
        return tools.format_amount(self.env, amount or 0.0, currency)


class GrCustomerApprovalMixin(models.AbstractModel):
    _name = 'gr.customer.approval.mixin'
    _inherit = 'gr.document.report.helper'
    _description = 'Customer Approval (signature or OTP) mixin'

    approval_state = fields.Selection([
        ('pending', 'Pending Approval'), ('sent', 'Code Sent'),
        ('approved', 'Approved'),
    ], string='Customer Approval', default='pending', copy=False,
        tracking=True, index=True)
    approval_method = fields.Selection([
        ('signature', 'Signed in person'),
        ('otp', 'Approved by one-time code'),
    ], string='Approval Method', readonly=True, copy=False)
    approval_partner_id = fields.Many2one(
        'res.partner', string='Approving Customer', copy=False,
        help='The customer who must approve this document.')
    approval_signature = fields.Binary(
        string='Approval Signature', attachment=False, copy=False)
    approval_signed_by = fields.Char(string='Signed By (name)', copy=False)
    approval_signed_by_role = fields.Char(
        string='Signer Role / Relationship', copy=False)
    approval_notes = fields.Text(string='Approval Notes', copy=False)
    approved_on = fields.Datetime(string='Approved On', readonly=True, copy=False)
    approved_by_uid = fields.Many2one(
        'res.users', string='Recorded By', readonly=True, copy=False)
    current_approval_document_id = fields.Many2one(
        'gr.customer.approval.document', string='Current Approval Copy',
        readonly=True, copy=False, ondelete='restrict')
    approval_log_count = fields.Integer(
        string='Approval History', compute='_compute_approval_counts')
    approval_document_count = fields.Integer(
        string='Approval Documents', compute='_compute_approval_counts')
    approval_email_count = fields.Integer(
        string='Emails Sent', compute='_compute_approval_counts')

    otp_code_hash = fields.Char(
        string='One-time Code Hash', copy=False, groups='base.group_system')
    otp_salt = fields.Char(
        string='One-time Code Salt', copy=False, groups='base.group_system')
    otp_channel = fields.Selection([
        ('email', 'Email'), ('sms', 'SMS'), ('whatsapp', 'WhatsApp'),
    ], string='Send Code Via', default='email', copy=False)
    otp_sent_to = fields.Char(string='Code Sent To', readonly=True, copy=False)
    otp_expires_at = fields.Datetime(string='Code Expires', readonly=True, copy=False)
    otp_attempts = fields.Integer(string='Failed Attempts', default=0, copy=False)
    otp_input = fields.Char(
        string='Enter Code', copy=False,
        help='Type the code the customer received, then click Verify Code.')

    def _compute_approval_counts(self):
        Log = self.env['gr.customer.approval.log'].sudo()
        Document = self.env['gr.customer.approval.document'].sudo()
        Message = self.env['mail.message'].sudo()
        for rec in self:
            domain = [('document_model', '=', rec._name),
                      ('document_res_id', '=', rec.id)]
            rec.approval_log_count = Log.search_count(domain)
            rec.approval_document_count = Document.search_count(domain)
            rec.approval_email_count = Message.search_count([
                ('model', '=', rec._name), ('res_id', '=', rec.id),
                ('message_type', 'in', ('email', 'email_outgoing')),
            ])

    def _resolve_approval_partner(self):
        self.ensure_one()
        return self.approval_partner_id or self._get_approval_partner()

    def _get_approval_partner(self):
        self.ensure_one()
        return self.env['res.partner']

    def _approval_document_label(self):
        self.ensure_one()
        return self.display_name

    def _approval_report_type(self):
        raise NotImplementedError

    def _approval_report_xmlid(self):
        self.ensure_one()
        return {
            'rental_order': 'gr_customer_approval.action_report_approval_rental_agreement',
            'delivery': 'gr_customer_approval.action_report_approval_delivery',
            'visit': 'gr_customer_approval.action_report_approval_visit',
            'return': 'gr_customer_approval.action_report_approval_return',
        }[self._approval_report_type()]

    def _approval_core_fields(self):
        return set()

    def _approval_content_payload(self):
        self.ensure_one()
        return {'model': self._name, 'id': self.id, 'name': self.display_name}

    def _approval_content_hash(self):
        self.ensure_one()
        payload = json.dumps(
            self._approval_content_payload(), sort_keys=True,
            ensure_ascii=False, default=str, separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def _approval_language(self, customer=False):
        self.ensure_one()
        partner = self._resolve_approval_partner()
        requested = partner.lang if customer and partner else self.env.user.lang
        requested = requested or self.company_id.partner_id.lang or 'en_US'
        Lang = self.env['res.lang'].sudo()
        if Lang.search_count([('code', '=', requested)]):
            return requested
        # The exact locale is not installed. Fall back to any installed locale
        # of the same base language - 'ar_SY' -> 'ar_001' - before English,
        # rather than special-casing Arabic.
        base = requested.split('_', 1)[0]
        sibling = Lang.search([('code', '=like', base + '%')], limit=1)
        return sibling.code or 'en_US'

    def _approval_filename(self, report_type=None, lang=None, approved=False,
                           approval_copy=False, version=None):
        self.ensure_one()
        report_type = report_type or self._approval_report_type()
        lang = lang or self.env.context.get('lang') or self.env.lang
        # Filenames are user-facing text: they go through the catalogue like
        # anything else, in the document's own language.
        env = self.with_context(lang=lang).env if lang else self.env
        if report_type == 'rental_order':
            base_name = env._('Rental_Agreement')
            copy_name = env._('Rental_Approval_Copy')
        elif report_type == 'delivery':
            base_name = env._('Delivery_Report')
            copy_name = env._('Delivery_Approval_Copy')
        elif report_type == 'visit':
            base_name = env._('Visit_Report')
            copy_name = env._('Visit_Approval_Copy')
        else:
            base_name = env._('Return_Report')
            copy_name = env._('Return_Approval_Copy')
        if approved:
            prefix = env._('Approved_%s') % base_name
        elif approval_copy:
            prefix = copy_name
        else:
            prefix = base_name
        version_suffix = '_V%s' % version if version and version > 1 else ''
        reference = self._document_filename_reference()
        return '%s_%s%s.pdf' % (prefix, reference, version_suffix)

    def _approval_report_copy(self):
        self.ensure_one()
        copy_id = self.env.context.get('approval_document_id')
        approval_copy = self.env['gr.customer.approval.document'].sudo().browse(copy_id).exists()
        if approval_copy and (approval_copy.document_model != self._name
                              or approval_copy.document_res_id != self.id):
            return self.env['gr.customer.approval.document']
        return approval_copy

    def _approval_report_photos(self):
        self.ensure_one()
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
            ('mimetype', '=like', 'image/%'),
        ], order='id')

    def _approval_selection_label(self, field_name, value=None):
        self.ensure_one()
        value = value if value is not None else self[field_name]
        return dict(self._fields[field_name]._description_selection(self.env)).get(value, value or '')

    def _approval_display_text(self, text):
        """Translate fixed reference values when they are rendered in a PDF.

        Checklist names are stored as ordinary Char values by their source
        modules, so QWeb cannot translate them through ``t-field``. Keeping the
        mapping here translates only their presentation and leaves operational
        data untouched.
        """
        translations = {
            'OK': _('OK'),
            'Fail': _('Fail'),
            'N/A': _('N/A'),
            'Cabin': _('Cabin'),
            'Panel boards': _('Panel boards'),
            'Panel screen function': _('Panel screen function'),
            'Fan belt condition': _('Fan belt condition'),
            'Cabin doors': _('Cabin doors'),
            'Door locks': _('Door locks'),
            'Radiator condition': _('Radiator condition'),
            'Engine sounds': _('Engine sounds'),
            'Oil level & condition': _('Oil level & condition'),
            'Water level & condition': _('Water level & condition'),
            'Battery condition': _('Battery condition'),
            'Load conditions': _('Load conditions'),
            'Cabin exterior': _('Cabin exterior'),
            'Cabin interior': _('Cabin interior'),
            'Panel board and buttons condition': _('Panel board and buttons condition'),
            'Engine oil level and condition': _('Engine oil level and condition'),
            'Engine oil leaking': _('Engine oil leaking'),
            'Water coolant level and condition': _('Water coolant level and condition'),
            'Water coolant leaking': _('Water coolant leaking'),
            'Water coolant rubber hose condition': _('Water coolant rubber hose condition'),
            'Water coolant steel pipe condition': _('Water coolant steel pipe condition'),
            'Fuel leaking': _('Fuel leaking'),
            'Fuel tank cap availability': _('Fuel tank cap availability'),
            'Fan belt conditions': _('Fan belt conditions'),
            'Air filter conditions': _('Air filter conditions'),
            'Air filter housing and lock conditions': _('Air filter housing and lock conditions'),
            'Fan hub bearing and blades conditions': _('Fan hub bearing and blades conditions'),
            'Battery conditions': _('Battery conditions'),
            'Battery cables conditions': _('Battery cables conditions'),
            'Battery terminal conditions': _('Battery terminal conditions'),
            'Dash board error': _('Dash board error'),
            'Breaker lags and bolts conditions': _('Breaker lags and bolts conditions'),
            'Breaker switch conditions': _('Breaker switch conditions'),
            'Emissions / smoke': _('Emissions / smoke'),
            'Cranking time': _('Cranking time'),
            'Genset elevation': _('Genset elevation'),
            'Genset foundation': _('Genset foundation'),
            'Area located (dry or wet)': _('Area located (dry or wet)'),
            'Water pump leaking': _('Water pump leaking'),
        }
        return translations.get(text, text or '')

    def _approval_record_selection_text(self, record, field_name):
        value = record[field_name]
        label = dict(record._fields[field_name]._description_selection(
            record.env)).get(value, value or '')
        return self._approval_display_text(label)

    def _approval_report_status_label(self):
        self.ensure_one()
        if self.env.context.get('operational_report') and 'state' in self._fields:
            return dict(self._fields['state']._description_selection(
                self.env)).get(self.state, self.state or '')
        approval_copy = self._approval_report_copy()
        if approval_copy:
            return dict(approval_copy._fields['state']._description_selection(
                approval_copy.env)).get(approval_copy.state, approval_copy.state)
        return _('Draft')

    def _approval_customer_representative(self):
        self.ensure_one()
        acknowledged = self.customer_ack_name if 'customer_ack_name' in self._fields else False
        return self.approval_signed_by or acknowledged or ''

    def _approval_attachment_url(self, attachment):
        self.ensure_one()
        if not attachment:
            # Odoo 19 renders every mail template once against a bare record to
            # validate it (mail.template._check_can_be_rendered); at that point
            # there is no approval copy and so no attachment.
            return ''
        token = attachment.sudo().with_context(
            approval_document_internal=True).generate_access_token()[0]
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return '%s/web/content/%s/%s?download=true&access_token=%s' % (
            base_url, attachment.id, quote(attachment.name or '', safe=''), token)

    def _render_approval_pdf(self, approval_copy=False, lang=False):
        self.ensure_one()
        lang = lang or (approval_copy.language if approval_copy else self._approval_language())
        context = dict(self.env.context, lang=lang, force_report_rendering=True)
        if approval_copy:
            context['approval_document_id'] = approval_copy.id
        return self.env['ir.actions.report'].sudo().with_context(**context)._render_qweb_pdf(
            self._approval_report_xmlid(), [self.id])[0]

    def _approval_versions(self):
        self.ensure_one()
        return self.env['gr.customer.approval.document'].sudo().search([
            ('document_model', '=', self._name),
            ('document_res_id', '=', self.id),
            ('report_type', '=', self._approval_report_type()),
        ])

    def _supersede_current_approval_copy(self, description=None):
        self.ensure_one()
        approval_copy = self.current_approval_document_id.sudo()
        if approval_copy and approval_copy.state == 'pending':
            approval_copy.with_context(approval_document_internal=True).write({
                'state': 'superseded',
            })
            self._approval_log(
                'superseded',
                description or _('The approval copy was superseded because the document changed.'),
                approval_document=approval_copy)
        self.with_context(skip_customer_approval_lock=True).write({
            'current_approval_document_id': False,
            'approval_state': 'pending', 'approval_method': False,
            'approved_on': False, 'approved_by_uid': False,
            'otp_code_hash': False, 'otp_salt': False, 'otp_input': False,
            'otp_attempts': 0, 'otp_expires_at': False, 'otp_sent_to': False,
        })

    def _validate_approval_copy(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id.sudo()
        if not approval_copy or not approval_copy.attachment_id:
            raise UserError(_('Generate an approval copy before approving this document.'))
        if approval_copy.state != 'pending':
            raise UserError(_('This approval copy is no longer valid. Generate a new version.'))
        if approval_copy.content_hash != self._approval_content_hash():
            self._supersede_current_approval_copy()
            raise UserError(_(
                'The document changed after the approval PDF was generated. '
                'The old copy was superseded; generate a new approval copy.'))
        return approval_copy

    def _approval_related_change_guard(self):
        """Protect/invalidate a PDF when a nested line changes."""
        if self.env.context.get('skip_customer_approval_lock'):
            return
        for rec in self:
            if rec.approval_state == 'approved':
                raise UserError(_(
                    'This approved document is locked. Create a new revision '
                    'before changing its lines or attachments.'))
            if rec.current_approval_document_id:
                rec._supersede_current_approval_copy()

    def _generate_approval_copy(self, language=None):
        self.ensure_one()
        if self.approval_state == 'approved':
            raise UserError(_('Create a new revision before generating another approval copy.'))
        language = language or self._approval_language()
        current = self.current_approval_document_id.sudo()
        content_hash = self._approval_content_hash()
        if current and current.state == 'pending' and current.content_hash == content_hash \
                and current.language == language and current.attachment_id:
            return current
        if current:
            self._supersede_current_approval_copy()
        versions = self._approval_versions()
        version = (max(versions.mapped('version')) if versions else 0) + 1
        filename = self._approval_filename(
            lang=language, approval_copy=True, version=version)
        approval_copy = self.env['gr.customer.approval.document'].sudo().with_context(
            approval_document_internal=True).create({
                'name': filename,
                'report_type': self._approval_report_type(),
                'document_model': self._name,
                'document_res_id': self.id,
                'document_number': self.display_name,
                'document_ref': self._approval_document_label(),
                'partner_id': self._resolve_approval_partner().id,
                'company_id': self.company_id.id,
                'language': language,
                'version': version,
                'state': 'pending',
                'content_hash': content_hash,
                'generated_at': fields.Datetime.now(),
            })
        pdf = self.with_context(lang=language)._render_approval_pdf(approval_copy, language)
        attachment = self.env['ir.attachment'].sudo().with_context(
            approval_document_internal=True).create({
                'name': filename, 'raw': pdf, 'mimetype': 'application/pdf',
                'res_model': self._name, 'res_id': self.id,
                'description': 'Customer approval copy v%s' % version,
            })
        approval_copy.with_context(approval_document_internal=True).write({
            'attachment_id': attachment.id,
            'file_hash': hashlib.sha256(pdf).hexdigest(),
        })
        self.with_context(skip_customer_approval_lock=True).write({
            'current_approval_document_id': approval_copy.id,
            'approval_state': 'pending',
        })
        self._approval_log(
            'generated',
            _('Approval PDF version %(version)s was generated in %(language)s.',
              version=version, language=language),
            approval_document=approval_copy)
        self._post_approval_note(_(
            'approval PDF version %(version)s generated', version=version))
        return approval_copy

    def action_generate_approval_copy(self):
        self.ensure_one()
        return self._generate_approval_copy().action_view_copy()

    def _finalize_approved_copy(self, method, approval_log):
        self.ensure_one()
        approval_copy = self.current_approval_document_id.sudo()
        approval_copy.with_context(approval_document_internal=True).write({
            'state': 'approved', 'approved_at': self.approved_on,
            'approval_method': method,
            'approval_channel': self.otp_channel if method == 'otp' else False,
            'approval_recipient': self.otp_sent_to if method == 'otp' else False,
            'approval_log_id': approval_log.id,
        })
        pdf = self.with_context(lang=approval_copy.language)._render_approval_pdf(
            approval_copy, approval_copy.language)
        filename = self._approval_filename(
            report_type=approval_copy.report_type, lang=approval_copy.language,
            approved=True, version=approval_copy.version)
        attachment = self.env['ir.attachment'].sudo().with_context(
            approval_document_internal=True).create({
                'name': filename, 'raw': pdf, 'mimetype': 'application/pdf',
                'res_model': self._name, 'res_id': self.id,
                'description': 'Approved customer document v%s' % approval_copy.version,
            })
        approval_copy.with_context(approval_document_internal=True).write({
            'name': filename,
            'approved_attachment_id': attachment.id,
            'approved_file_hash': hashlib.sha256(pdf).hexdigest(),
        })

    def action_preview_document(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        if approval_copy and approval_copy.attachment_id:
            return approval_copy.action_view_copy()
        lang = self._approval_language()
        return self.env.ref(self._approval_report_xmlid()).with_context(lang=lang).report_action(self)

    def action_download_pdf(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        if approval_copy and approval_copy.attachment_id:
            return approval_copy.action_download_copy()
        return self.action_preview_document()

    def action_view_approval_copy(self):
        self.ensure_one()
        return self._validate_approval_copy().action_view_copy()

    def action_view_approved_document(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        if not approval_copy or not approval_copy.approved_attachment_id:
            raise UserError(_('No approved PDF is available for this document.'))
        return approval_copy.action_view_approved_document()

    def action_download_approved_document(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        if not approval_copy or not approval_copy.approved_attachment_id:
            raise UserError(_('No approved PDF is available for this document.'))
        return approval_copy.action_download_approved_document()

    def action_view_approval_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Approval Documents'),
            'res_model': 'gr.customer.approval.document', 'view_mode': 'list,form',
            'domain': [('document_model', '=', self._name),
                       ('document_res_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def action_view_approval_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Approval History'),
            'res_model': 'gr.customer.approval.log', 'view_mode': 'list,form',
            'domain': [('document_model', '=', self._name),
                       ('document_res_id', '=', self.id)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def action_view_approval_emails(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Emails Sent'),
            'res_model': 'mail.message', 'view_mode': 'list,form',
            'domain': [('model', '=', self._name), ('res_id', '=', self.id),
                       ('message_type', 'in', ('email', 'email_outgoing'))],
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def _approval_log(self, event_type, description='', method=False,
                      channel=False, recipient=False, approval_document=False):
        self.ensure_one()
        approval_method = method or self.approval_method
        approval_channel = channel or (
            self.otp_channel if approval_method == 'otp' else False)
        approval_recipient = recipient or (
            self.otp_sent_to if approval_channel else False)
        return self.env['gr.customer.approval.log'].sudo().create({
            'document_model': self._name, 'document_res_id': self.id,
            'document_ref': self.display_name,
            'partner_id': self._resolve_approval_partner().id,
            'approval_document_id': approval_document.id if approval_document else (
                self.current_approval_document_id.id or False),
            'event_type': event_type,
            'approval_method': approval_method,
            'channel': approval_channel,
            'recipient': approval_recipient,
            'attempts': self.otp_attempts, 'description': description,
            'user_id': self.env.user.id,
        })

    def _require_customer_approval(self, operation):
        self.ensure_one()
        if self.approval_state != 'approved' \
                or not self.current_approval_document_id.approved_attachment_id:
            raise UserError(_(
                'Customer approval of a valid PDF is required before %(operation)s.',
                operation=operation))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.approval_partner_id:
                partner = rec._get_approval_partner()
                if partner:
                    rec.approval_partner_id = partner
        return records

    def write(self, vals):
        internal = self.env.context.get('skip_customer_approval_lock')
        if vals and not internal:
            locked = _APPROVAL_LOCKED_FIELDS.intersection(vals)
            for rec in self:
                if rec.approval_state == 'approved' and (
                        locked or self._approval_core_fields().intersection(vals)):
                    raise UserError(_(
                        'This approved document is locked. Create a new revision '
                        'before changing approval or business data.'))
        tracked = self.filtered(lambda rec: rec.current_approval_document_id
                                and rec.approval_state != 'approved') if not internal else self.browse()
        before = {rec.id: rec._approval_content_hash() for rec in tracked}
        result = super().write(vals)
        for rec in tracked:
            if rec.exists() and before[rec.id] != rec._approval_content_hash():
                rec._supersede_current_approval_copy()
        return result

    def unlink(self):
        if self.filtered(lambda rec: rec.approval_state == 'approved'):
            raise UserError(_('Approved customer approval records cannot be deleted.'))
        return super().unlink()

    def action_approve_by_signature(self):
        for rec in self:
            if rec.approval_state == 'approved':
                raise UserError(_('This document is already approved.'))
            approval_copy = rec._validate_approval_copy()
            if not rec.approval_signature:
                raise UserError(_(
                    "Capture the customer's signature first, or send a one-time "
                    'code instead if they are not present.'))
            if not rec.approval_signed_by:
                raise UserError(_('Enter the name of the person who signed.'))
            rec.with_context(skip_customer_approval_lock=True).write({
                'approval_state': 'approved', 'approval_method': 'signature',
                'approved_on': fields.Datetime.now(),
                'approved_by_uid': self.env.user.id,
                'otp_code_hash': False, 'otp_salt': False, 'otp_input': False,
            })
            log = rec._approval_log(
                'approved',
                _('The fixed PDF was approved by customer signature.'),
                method='signature', approval_document=approval_copy)
            rec._finalize_approved_copy('signature', log)
            rec._post_approval_note(_('signed in person'))
        return True

    def _otp_destination(self):
        self.ensure_one()
        partner = self._resolve_approval_partner()
        if not partner:
            raise UserError(_('No customer is set on this document.'))
        if self.otp_channel == 'email':
            if not partner.email:
                raise UserError(_(
                    'Customer %s has no email address. Add one, or choose a '
                    'different channel.') % partner.display_name)
            return partner.email
        # Odoo 19 merged res.partner.mobile into res.partner.phone.
        number = partner.phone
        if not number:
            raise UserError(_(
                'Customer %s has no phone number. Add one, or send the code by '
                'email instead.') % partner.display_name)
        return number

    def _approval_mail_template_xmlid(self):
        self.ensure_one()
        return {
            'gr.rental.order': 'gr_customer_approval.mail_template_rental_order_approval_code',
            'gr.rental.inspection': 'gr_customer_approval.mail_template_inspection_approval_code',
            'gr.field.worksheet': 'gr_customer_approval.mail_template_worksheet_approval_code',
        }.get(self._name)

    def _approval_document_mail_template_xmlid(self):
        self.ensure_one()
        return {
            'gr.rental.order': 'gr_customer_approval.mail_template_rental_order_document',
            'gr.rental.inspection': 'gr_customer_approval.mail_template_inspection_document',
            'gr.field.worksheet': 'gr_customer_approval.mail_template_worksheet_document',
        }.get(self._name)

    def _approval_email_subject(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        return self.env._(
            'Approval code for %(document)s - Version %(version)s',
            document=self._approval_document_label(),
            version=approval_copy.version)

    def _approval_email_body_html(self):
        self.ensure_one()
        code = self.env.context.get('approval_code') or ''
        approval_copy = self.current_approval_document_id
        link = self._approval_attachment_url(approval_copy.attachment_id)
        return Markup(
            "<div style='font-family:Arial,sans-serif;font-size:14px;'>"
            '<p>%s</p><p>%s</p><p><a href="%s">%s</a></p>'
            "<p style='font-size:26px;font-weight:bold;letter-spacing:3px;color:#176b67;'>%s</p>"
            '<p>%s</p><p>%s</p></div>'
        ) % (
            tools.html_escape(self.env._('Dear Customer,')),
            tools.html_escape(self.env._(
                'Please review %(document)s, version %(version)s, before using '
                'the code. The code approves this exact attached PDF only.',
                document=self._approval_document_label(), version=approval_copy.version)),
            tools.html_escape(link),
            tools.html_escape(self.env._('Review approval document')),
            tools.html_escape(code),
            tools.html_escape(self.env._(
                'The code is valid for %(minutes)s minutes. Do not use it until '
                'you have reviewed the document.', minutes=OTP_VALID_MINUTES)),
            tools.html_escape(self.env._(
                'If you did not expect this message, please ignore it.')),
        )

    def _approval_document_email_subject(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        return self.env._(
            '%(document)s - Version %(version)s',
            document=self._approval_document_label(), version=approval_copy.version)

    def _approval_document_email_body_html(self):
        self.ensure_one()
        approval_copy = self.current_approval_document_id
        attachment = approval_copy.approved_attachment_id or approval_copy.attachment_id
        link = self._approval_attachment_url(attachment)
        return Markup(
            "<div style='font-family:Arial,sans-serif;font-size:14px;'>"
            '<p>%s</p><p>%s</p><p><a href="%s">%s</a></p><p>%s</p></div>'
        ) % (
            tools.html_escape(self.env._('Dear Customer,')),
            tools.html_escape(self.env._(
                'Attached is %(document)s, version %(version)s.',
                document=self._approval_document_label(), version=approval_copy.version)),
            tools.html_escape(link),
            tools.html_escape(self.env._('View document')),
            tools.html_escape(self.env._('Regards,')),
        )

    def _send_template_with_copy(self, template_xmlid, destination, extra_context=None):
        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            raise UserError(_('No approval email template is configured.'))
        approval_copy = self.current_approval_document_id
        attachment = approval_copy.approved_attachment_id or approval_copy.attachment_id
        context = dict(extra_context or {}, lang=approval_copy.language)
        template.with_context(**context).send_mail(
            self.id, force_send=True,
            email_values={
                'email_to': destination,
                'attachment_ids': [(4, attachment.id)],
            })

    def _send_otp_via_channel(self, code, destination):
        self.ensure_one()
        if self.otp_channel == 'email':
            self._send_template_with_copy(
                self._approval_mail_template_xmlid(), destination,
                {'approval_code': code})
            return True
        raise UserError(_(
            'Sending codes by %s is not connected yet. Use Email for now; the '
            'channel can be enabled later without changing this document.')
            % dict(self._fields['otp_channel'].selection).get(self.otp_channel))

    def action_send_document_to_customer(self):
        for rec in self:
            partner = rec._resolve_approval_partner()
            if not partner or not partner.email:
                raise UserError(_('The customer must have an email address.'))
            customer_lang = rec._approval_language(customer=True)
            approval_copy = rec.current_approval_document_id
            if not approval_copy or (
                    approval_copy.state == 'pending' and approval_copy.language != customer_lang):
                approval_copy = rec._generate_approval_copy(language=customer_lang)
            if approval_copy.content_hash != rec._approval_content_hash():
                rec._supersede_current_approval_copy()
                approval_copy = rec._generate_approval_copy(language=customer_lang)
            rec._send_template_with_copy(
                rec._approval_document_mail_template_xmlid(), partner.email)
            approval_copy.with_context(approval_document_internal=True).write({
                'sent_count': approval_copy.sent_count + 1,
                'last_sent_at': fields.Datetime.now(),
            })
            rec._approval_log(
                'document_sent', _('The PDF document was sent to the customer.'),
                channel='email', recipient=_mask_destination(partner.email, 'email'),
                approval_document=approval_copy)
        return True

    def action_send_otp(self):
        for rec in self:
            if rec.approval_state == 'approved':
                raise UserError(_('This document is already approved.'))
            customer_lang = rec._approval_language(customer=True)
            if not rec.current_approval_document_id \
                    or rec.current_approval_document_id.language != customer_lang:
                rec._generate_approval_copy(language=customer_lang)
            rec._validate_approval_copy()
            destination = rec._otp_destination()
            code = ''.join(secrets.choice('0123456789') for _ in range(OTP_LENGTH))
            salt = secrets.token_hex(16)
            masked = _mask_destination(destination, rec.otp_channel)
            rec._send_otp_via_channel(code, destination)
            rec.with_context(skip_customer_approval_lock=True).write({
                'otp_code_hash': _hash_otp(code, salt), 'otp_salt': salt,
                'otp_sent_to': masked,
                'otp_expires_at': fields.Datetime.now() + timedelta(minutes=OTP_VALID_MINUTES),
                'otp_attempts': 0, 'otp_input': False, 'approval_state': 'sent',
            })
            rec._approval_log(
                'sent', _('An approval code was sent for the fixed PDF version.'),
                method='otp', channel=rec.otp_channel, recipient=masked)
            rec._post_approval_note(_('one-time code sent to %(dest)s', dest=masked))
        return True

    def _otp_failure_result(self, message):
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Code not accepted'), 'message': message,
                       'type': 'warning', 'sticky': False},
        }

    def action_verify_otp(self):
        self.ensure_one()
        rec = self
        if rec.approval_state == 'approved':
            raise UserError(_('This document is already approved.'))
        approval_copy = rec._validate_approval_copy()
        stored_hash, salt = rec.sudo().otp_code_hash, rec.sudo().otp_salt
        if not stored_hash or not salt:
            raise UserError(_('No code has been sent yet.'))
        if rec.otp_expires_at and fields.Datetime.now() > rec.otp_expires_at:
            return rec._otp_failure_result(_('That code has expired. Send a new one.'))
        if rec.otp_attempts >= OTP_MAX_ATTEMPTS:
            return rec._otp_failure_result(_('Too many incorrect attempts. Send a new code.'))
        input_code = (rec.otp_input or '').strip()
        if not input_code or _hash_otp(input_code, salt) != stored_hash:
            rec.with_context(skip_customer_approval_lock=True).write({
                'otp_attempts': rec.otp_attempts + 1,
            })
            rec._approval_log(
                'failed', _('The approval code was not accepted.'), method='otp',
                channel=rec.otp_channel, recipient=rec.otp_sent_to)
            remaining = max(OTP_MAX_ATTEMPTS - rec.otp_attempts, 0)
            message = _(
                'That code is not correct, and there are no attempts left. Send a new code.'
            ) if not remaining else _(
                'That code is not correct. %s attempt(s) remaining.') % remaining
            return rec._otp_failure_result(message)
        rec.sudo().with_context(skip_customer_approval_lock=True).write({
            'approval_state': 'approved', 'approval_method': 'otp',
            'approved_on': fields.Datetime.now(), 'approved_by_uid': self.env.user.id,
            'otp_code_hash': False, 'otp_salt': False, 'otp_input': False,
        })
        log = rec._approval_log(
            'approved', _('The fixed PDF was approved using a one-time code.'),
            method='otp', channel=rec.otp_channel, recipient=rec.otp_sent_to,
            approval_document=approval_copy)
        rec._finalize_approved_copy('otp', log)
        rec._post_approval_note(_(
            'approved by one-time code sent to %(dest)s', dest=rec.otp_sent_to))
        return True

    def action_reset_approval(self):
        for rec in self:
            if rec.approval_state == 'approved' and not (
                    self.env.user.has_group('gr_security_base.group_generator_general_manager')
                    or self.env.user.has_group('gr_security_base.group_generator_administrator')
                    or self.env.user.has_group('base.group_system')
                    or self.env.is_superuser()):
                raise UserError(_(
                    'Only a General Manager or Generator Administrator can cancel '
                    'an approved customer approval.'))
            approval_copy = rec.current_approval_document_id.sudo()
            if approval_copy:
                approval_copy.with_context(approval_document_internal=True).write({
                    'state': 'cancelled' if approval_copy.state == 'approved' else 'superseded',
                })
            rec.with_context(skip_customer_approval_lock=True).write({
                'approval_state': 'pending', 'approval_method': False,
                'approved_on': False, 'approved_by_uid': False,
                'approval_signature': False, 'otp_code_hash': False,
                'otp_salt': False, 'otp_input': False, 'otp_attempts': 0,
                'otp_expires_at': False, 'otp_sent_to': False,
                'current_approval_document_id': False,
            })
            rec._approval_log(
                'cancelled',
                _('The customer approval was cancelled and a new approval is required.'),
                approval_document=approval_copy)
        return True

    def action_create_new_revision(self):
        self.ensure_one()
        old = self.current_approval_document_id
        if self.approval_state == 'approved':
            self.action_reset_approval()
        elif old:
            self._supersede_current_approval_copy()
        self._approval_log(
            'revision', _('A new approval document revision was requested.'),
            approval_document=old)
        return self._generate_approval_copy().action_view_copy()

    def _post_approval_note(self, what):
        self.ensure_one()
        if hasattr(self, 'message_post'):
            self.message_post(
                body=_('Customer approval: %(doc)s - %(what)s.',
                       doc=self._approval_document_label(), what=what),
                subtype_xmlid='mail.mt_note')

    @api.constrains('otp_channel')
    def _check_channel(self):
        for rec in self:
            if rec.otp_channel not in ('email', 'sms', 'whatsapp'):
                raise ValidationError(_('Unknown code channel.'))
