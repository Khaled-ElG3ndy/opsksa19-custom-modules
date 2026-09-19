# -*- coding: utf-8 -*-
from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrCustomerApprovalDocument(models.Model):
    _name = 'gr.customer.approval.document'
    _description = 'Customer Approval Document Version'
    _order = 'document_model, document_res_id, version desc, id desc'

    name = fields.Char(string='File Name', required=True, readonly=True)
    report_type = fields.Selection([
        ('rental_order', 'Rental Agreement'),
        ('delivery', 'Delivery Report'),
        ('visit', 'Visit Report'),
        ('return', 'Return Report'),
    ], string='Document Type', required=True, readonly=True, index=True)
    document_model = fields.Char(string='Document Model', required=True, readonly=True, index=True)
    document_res_id = fields.Integer(string='Document ID', required=True, readonly=True, index=True)
    document_number = fields.Char(string='Document Number', required=True, readonly=True, index=True)
    document_ref = fields.Char(string='Document Reference', required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True)
    language = fields.Char(string='Document Language', required=True, readonly=True)
    version = fields.Integer(string='Version', required=True, readonly=True)
    state = fields.Selection([
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
        ('superseded', 'Superseded'),
    ], string='Status', required=True, default='pending', readonly=True, index=True)
    attachment_id = fields.Many2one(
        'ir.attachment', string='Approval Copy', readonly=True, copy=False,
        ondelete='restrict')
    approved_attachment_id = fields.Many2one(
        'ir.attachment', string='Approved Document', readonly=True, copy=False,
        ondelete='restrict')
    content_hash = fields.Char(string='Content Hash', required=True, readonly=True, index=True)
    file_hash = fields.Char(string='File Hash', readonly=True, index=True)
    approved_file_hash = fields.Char(string='Approved File Hash', readonly=True, index=True)
    generated_at = fields.Datetime(string='Generated On', required=True, readonly=True)
    approved_at = fields.Datetime(string='Approved On', readonly=True)
    approval_method = fields.Selection([
        ('signature', 'Signed in person'),
        ('otp', 'Approved by one-time code'),
    ], string='Approval Method', readonly=True)
    approval_channel = fields.Selection([
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('whatsapp', 'WhatsApp'),
    ], string='Approval Channel', readonly=True)
    approval_recipient = fields.Char(string='Approval Recipient', readonly=True)
    approval_log_id = fields.Many2one(
        'gr.customer.approval.log', string='Approval Log Entry', readonly=True,
        ondelete='restrict')
    sent_count = fields.Integer(string='Times Sent', readonly=True)
    last_sent_at = fields.Datetime(string='Last Sent On', readonly=True)

    _document_version_uniq = models.Constraint(
        'unique(document_model, document_res_id, report_type, version)',
        "A document version can only be created once.",
    )

    def _source_record(self):
        self.ensure_one()
        return self.env[self.document_model].browse(self.document_res_id).exists()

    def action_open_source(self):
        self.ensure_one()
        source = self._source_record()
        if not source:
            raise UserError(_('The source document no longer exists.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.document_model,
            'res_id': source.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _attachment_url(self, attachment, download=False):
        self.ensure_one()
        if not attachment:
            raise UserError(_('The PDF file has not been generated yet.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s?download=%s' % (
                attachment.id, quote(attachment.name or '', safe=''),
                'true' if download else 'false'),
            'target': 'self' if download else 'new',
        }

    def action_view_copy(self):
        self.ensure_one()
        return self._attachment_url(self.attachment_id)

    def action_download_copy(self):
        self.ensure_one()
        return self._attachment_url(self.attachment_id, download=True)

    def action_view_approved_document(self):
        self.ensure_one()
        return self._attachment_url(self.approved_attachment_id)

    def action_download_approved_document(self):
        self.ensure_one()
        return self._attachment_url(self.approved_attachment_id, download=True)

    def write(self, vals):
        if vals and not self.env.context.get('approval_document_internal'):
            raise UserError(_('Approval document versions cannot be edited manually.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda record: record.state == 'approved' or record.approved_attachment_id):
            raise UserError(_('Approved document versions cannot be deleted.'))
        if not self.env.context.get('approval_document_internal'):
            raise UserError(_('Approval document versions cannot be deleted manually.'))
        return super().unlink()


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    _APPROVAL_PDF_PROTECTED_FIELDS = frozenset({
        'name', 'company_id', 'public', 'res_model', 'res_id', 'res_field',
        'type', 'url', 'raw', 'datas', 'db_datas', 'store_fname',
        'file_size', 'checksum', 'index_content', 'mimetype',
    })
    _APPROVAL_SOURCE_ATTACHMENT_FIELDS = frozenset({
        'res_model', 'res_id', 'res_field', 'type', 'url', 'raw', 'datas',
        'db_datas', 'store_fname', 'file_size', 'checksum', 'index_content',
        'mimetype',
    })

    def _approval_source_documents(self):
        sources = {}
        for attachment in self:
            if attachment.res_model in {
                    'gr.rental.order', 'gr.rental.inspection', 'gr.field.worksheet'} \
                    and attachment.res_id:
                sources.setdefault(attachment.res_model, set()).add(attachment.res_id)
        records = []
        for model_name, ids in sources.items():
            records.append(self.env[model_name].browse(ids).exists())
        return records

    def _approval_document_versions(self):
        if not self.ids or 'gr.customer.approval.document' not in self.env:
            return self.env['gr.customer.approval.document']
        return self.env['gr.customer.approval.document'].sudo().search([
            '|',
            ('attachment_id', 'in', self.ids),
            ('approved_attachment_id', 'in', self.ids),
        ])

    def _approval_version_attachments(self, versions):
        return (
            versions.mapped('attachment_id')
            | versions.mapped('approved_attachment_id')
        ) & self

    def write(self, vals):
        if vals and not self.env.context.get('approval_document_internal'):
            approval_attachments = self._approval_version_attachments(
                self._approval_document_versions())
            if approval_attachments and (
                    self._APPROVAL_PDF_PROTECTED_FIELDS.intersection(vals)):
                raise UserError(_('Approval PDF attachments cannot be replaced or edited.'))
            source_attachments = self - approval_attachments
            if self._APPROVAL_SOURCE_ATTACHMENT_FIELDS.intersection(vals):
                for documents in source_attachments._approval_source_documents():
                    documents._approval_related_change_guard()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('approval_document_internal'):
            sources = {}
            guarded_fields = self._APPROVAL_SOURCE_ATTACHMENT_FIELDS
            for vals in vals_list:
                if not guarded_fields.intersection(vals):
                    continue
                model_name = vals.get('res_model')
                res_id = vals.get('res_id')
                if model_name in {
                        'gr.rental.order', 'gr.rental.inspection',
                        'gr.field.worksheet'} and res_id:
                    sources.setdefault(model_name, set()).add(res_id)
            for model_name, ids in sources.items():
                self.env[model_name].browse(ids)._approval_related_change_guard()
        return super().create(vals_list)

    def unlink(self):
        if self._approval_document_versions():
            raise UserError(_('Approval PDF attachments cannot be deleted.'))
        if not self.env.context.get('approval_document_internal'):
            for documents in self._approval_source_documents():
                documents._approval_related_change_guard()
        return super().unlink()
