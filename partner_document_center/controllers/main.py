# -*- coding: utf-8 -*-
"""Upload endpoint for the Document Center.

Multipart rather than base64-over-JSON so that a large file is streamed
instead of inflated by a third in the browser.  The attachment it creates is
an ordinary ``ir.attachment`` on an ordinary record - it shows up in that
record's chatter exactly like a file dropped there by hand.
"""

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class PartnerDocumentCenterController(http.Controller):

    @http.route('/partner_document_center/upload', type='http', auth='user',
                methods=['POST'], csrf=True)
    def upload(self, ufile, partner_id, target_model=None, target_id=None, **kwargs):
        """Attach a file to the contact, or to one of that contact's records.

        Every parameter is re-validated server-side:

        * the contact must exist and be *writable* by the caller;
        * a target record, when given, must belong to a registered source, must
          genuinely belong to this contact, and must be writable too.

        Without the second check a crafted request could park a file on any
        record id in the database.
        """
        try:
            partner = request.env['res.partner'].browse(int(partner_id)).exists()
            if not partner:
                raise UserError(_("Unknown contact."))
            # Uploading is a modification of the contact's file set: require
            # write, not just read.
            partner.check_access('write')

            res_model, res_id = 'res.partner', partner.id
            if target_model and target_id:
                res_model, res_id = self._validate_target(partner, target_model, int(target_id))

            attachment = request.env['ir.attachment'].create({
                'name': ufile.filename,
                'raw': ufile.read(),
                'res_model': res_model,
                'res_id': res_id,
            })

            category_id = kwargs.get('category_id')
            if category_id and category_id != 'false':
                request.env['partner.document.center'].action_set_metadata(
                    attachment.id, {'category_id': int(category_id)})
        except (AccessError, UserError) as error:
            # Shape expected by web's file_upload service, so the message the
            # user sees is ours and not a generic "an error occured".
            return request.make_json_response({'error': {'message': str(error)}}, status=403)
        except ValueError:
            return request.make_json_response(
                {'error': {'message': _("Invalid request.")}}, status=400)

        return request.make_json_response({
            'attachment_id': attachment.id,
            'name': attachment.name,
        })

    def _validate_target(self, partner, model_name, res_id):
        """Prove that ``res_id`` is a record of ``model_name`` owned by ``partner``."""
        Source = request.env['partner.document.source']
        source = next(
            (s for s in Source._get_available_sources() if s['model'] == model_name),
            None,
        )
        if not source:
            raise UserError(_("Files cannot be attached to this kind of record."))

        Center = request.env['partner.document.center']
        partner_ids = Center._resolve_partner_ids(partner, 'commercial')
        domain = Source._get_source_record_domain(source, partner_ids) + [('id', '=', res_id)]
        # search() applies the model's ACL and record rules: a record the user
        # cannot see simply is not found.
        record = request.env[model_name].search(domain, limit=1)
        if not record:
            raise UserError(_("This record does not belong to this contact."))
        record.check_access('write')
        return model_name, record.id
