# -*- coding: utf-8 -*-
"""Side-car metadata for attachments shown in the Document Center.

The attachment itself is never touched or copied: this model only carries the
two pieces of UI state the Document Center adds (a category and an "important"
flag), keyed by ``ir.attachment``.  Deleting the attachment deletes the
metadata, never the other way round.
"""
from odoo import api, fields, models
from odoo.exceptions import AccessError


class PartnerDocumentMetadata(models.Model):
    _name = 'partner.document.metadata'
    _description = 'Partner Document Metadata'
    _rec_name = 'attachment_id'

    attachment_id = fields.Many2one(
        'ir.attachment', required=True, ondelete='cascade', index=True,
    )
    category_id = fields.Many2one(
        'partner.document.category', string='Category', ondelete='set null', index=True,
    )
    is_important = fields.Boolean(string='Important', index=True)
    company_id = fields.Many2one(
        'res.company', related='attachment_id.company_id', store=True, index=True,
    )

    _attachment_uniq = models.Constraint(
        'unique(attachment_id)',
        "An attachment can only carry one Document Center metadata record.",
    )

    @api.model
    def _get_or_create(self, attachment):
        """Return the metadata row of ``attachment``, creating it on demand."""
        attachment.check_access('write')
        metadata = self.search([('attachment_id', '=', attachment.id)], limit=1)
        if not metadata:
            metadata = self.create({'attachment_id': attachment.id})
        return metadata

    def _assert_attachment_writable(self):
        """Annotating a document requires write access to that document.

        Enforced on the model rather than only in the Document Center's own
        methods, because this model is reachable over RPC like any other: a
        user who may merely *read* an invoice must not be able to re-label or
        star its attachment by calling create/write directly.
        """
        for record in self:
            attachment = record.attachment_id
            if not attachment.has_access('write'):
                raise AccessError(self.env._(
                    "You are not allowed to access the document this metadata refers to."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._assert_attachment_writable()
        return records

    def write(self, vals):
        self._assert_attachment_writable()
        result = super().write(vals)
        if 'attachment_id' in vals:
            # Re-check: the row must not be re-pointed at a document the user
            # cannot modify either.
            self._assert_attachment_writable()
        return result

    def unlink(self):
        self._assert_attachment_writable()
        return super().unlink()
