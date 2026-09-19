# -*- coding: utf-8 -*-
"""RPC surface of the Document Center.

Every entry point starts by proving the caller may read *this* partner, then
delegates to the engine.  Nothing here trusts an id coming from the browser.
"""
from odoo import _, api, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _check_document_center_access(self):
        """Read access on the contact is the ticket into its Document Center."""
        self.ensure_one()
        self.check_access('read')
        return self

    def action_fetch_documents(self, options=None):
        """Return one page of aggregated documents. Called from the OWL client."""
        self._check_document_center_access()
        return self.env['partner.document.center'].fetch_documents(self, options or {})

    def action_count_documents(self, scope='self'):
        """Total document count, for the smart button.

        Deliberately not a computed field: it would run one COUNT per source on
        every contact form load, including list views. The client asks for it
        after the form is painted instead.
        """
        self._check_document_center_access()
        return self.env['partner.document.center'].count_documents(self, scope)

    def action_open_document_center(self):
        """Smart-button action: the Document Center, full width."""
        self._check_document_center_access()
        return {
            'type': 'ir.actions.client',
            'tag': 'partner_document_center',
            'name': _("Document Center"),
            'params': {
                'partner_id': self.id,
                'partner_name': self.display_name,
            },
        }

    @api.model
    def action_upload_document_target_records(self, partner_id, source_code, query='', limit=20):
        """Records of one source this partner owns, for the "link to an existing
        document" selector of the upload dialog.

        Only records reachable from *this* partner and readable by the caller
        are ever returned, so the selector cannot be used to enumerate the
        database.
        """
        partner = self.browse(int(partner_id)).exists()
        if not partner:
            return []
        partner._check_document_center_access()

        Source = self.env['partner.document.source']
        source = next(
            (s for s in Source._get_available_sources() if s['code'] == source_code),
            None,
        )
        if not source or source['model'] == 'res.partner':
            return []

        Center = self.env['partner.document.center']
        partner_ids = Center._resolve_partner_ids(partner, 'commercial')
        domain = Source._get_source_record_domain(source, partner_ids)
        Model = self.env[source['model']]
        if query:
            rec_name = Model._rec_name
            rec_field = Model._fields.get(rec_name) if rec_name else None
            if rec_field is not None and rec_field.store and rec_field.type in ('char', 'text'):
                domain = domain + [(rec_name, 'ilike', query)]
        records = Model.search(domain, limit=max(1, min(int(limit), 50)), order='id desc')
        return [
            {'id': record.id, 'display_name': record.display_name}
            for record in records
        ]
