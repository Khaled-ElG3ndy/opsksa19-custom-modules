# -*- coding: utf-8 -*-
"""Aggregation engine behind the partner Document Center.

Security model
--------------
Everything goes through ``ir.attachment.search()`` with the *user's* own
environment.  In Odoo 19 ``ir.attachment._search()`` already cascades the
access check down to the referenced record (see
``ir_attachment._check_access`` / ``_search`` in ``base``): an attachment is
only returned if the user may read the record it hangs on.  Pinning exactly
one ``res_model`` per query makes that cascade collapse into a single SQL
sub-select instead of the batched Python fallback, which is why the engine
queries one source at a time rather than OR-ing every source into one domain.

The consequence is that this module contains no ACL logic of its own and never
needs ``sudo()`` to read documents: if the user cannot open the invoice, the
invoice's attachment simply never comes back from the search.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.tools import formatLang

# Mimetypes that carry no information (uploaded by a browser that could not
# guess). For these - and only these - we fall back to the file extension.
AMBIGUOUS_MIMETYPES = {
    '', False, None,
    'application/octet-stream',
    'binary/octet-stream',
    'application/binary',
}

MIMETYPE_FILE_TYPES = {
    'application/pdf': 'pdf',
    'application/x-pdf': 'pdf',
    'application/vnd.ms-excel': 'excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
    'application/vnd.oasis.opendocument.spreadsheet': 'excel',
    'text/csv': 'excel',
    'application/msword': 'word',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
    'application/vnd.oasis.opendocument.text': 'word',
    'application/rtf': 'word',
}

EXTENSION_FILE_TYPES = {
    'pdf': 'pdf',
    'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
    'bmp': 'image', 'webp': 'image', 'svg': 'image', 'tif': 'image', 'tiff': 'image',
    'xls': 'excel', 'xlsx': 'excel', 'csv': 'excel', 'ods': 'excel',
    'doc': 'word', 'docx': 'word', 'odt': 'word', 'rtf': 'word',
}

# "documents" in the KPI header groups everything that is neither an image nor
# a PDF but is still a readable document.
DOCUMENT_FILE_TYPES = ('excel', 'word')

VALID_ORDERS = (
    'date_desc', 'date_asc', 'name_asc', 'name_desc',
    'size_desc', 'size_asc', 'source',
)
VALID_SCOPES = ('self', 'commercial')
VALID_FILE_TYPES = ('all', 'pdf', 'image', 'excel', 'word', 'other')
VALID_DATE_RANGES = ('all', 'today', 'week', 'month', 'year', 'custom')
# Live business records vs stored files. "all" shows both.
VALID_DOC_KINDS = ('all', 'record', 'attachment')


class PartnerDocumentCenter(models.AbstractModel):
    _name = 'partner.document.center'
    _description = 'Partner Document Center'

    # Upper bound on the rows scanned per source for one request. A partner
    # with more documents than this in a single source still works: the list,
    # the counters and the pagination stay consistent with each other, they
    # just describe the most recent _MAX_SCAN rows and the response carries
    # ``truncated: true`` so the UI can say so.
    _MAX_SCAN = 20000
    _DEFAULT_LIMIT = 40
    _MAX_LIMIT = 200

    # ------------------------------------------------------------------
    # Option sanitising - nothing from the client is trusted
    # ------------------------------------------------------------------
    @api.model
    def _sanitise_options(self, options):
        options = dict(options or {})
        scope = options.get('scope')
        file_type = options.get('file_type')
        date_range = options.get('date_range')
        order = options.get('order')

        try:
            limit = int(options.get('limit') or self._DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = self._DEFAULT_LIMIT
        try:
            offset = int(options.get('offset') or 0)
        except (TypeError, ValueError):
            offset = 0
        try:
            category_id = int(options['category_id']) if options.get('category_id') else False
        except (TypeError, ValueError):
            category_id = False

        doc_kind = options.get('doc_kind')
        return {
            'scope': scope if scope in VALID_SCOPES else 'self',
            'source': options.get('source') or 'all',
            'doc_kind': doc_kind if doc_kind in VALID_DOC_KINDS else 'all',
            'file_type': file_type if file_type in VALID_FILE_TYPES else 'all',
            'date_range': date_range if date_range in VALID_DATE_RANGES else 'all',
            'date_from': options.get('date_from') or False,
            'date_to': options.get('date_to') or False,
            'search': (options.get('search') or '').strip(),
            'category_id': category_id,
            'important_only': bool(options.get('important_only')),
            'order': order if order in VALID_ORDERS else 'date_desc',
            'limit': max(1, min(limit, self._MAX_LIMIT)),
            'offset': max(0, offset),
        }

    # ------------------------------------------------------------------
    # Partner scope
    # ------------------------------------------------------------------
    @api.model
    def _resolve_partner_ids(self, partner, scope):
        """Partner ids covered by ``scope``.

        ``self``        only this contact.
        ``commercial``  the commercial entity this contact belongs to, plus
                        every contact attached to it. ``commercial_partner_id``
                        is Odoo's own notion of "the company this address
                        belongs to", so this never mixes two unrelated
                        commercial entities.

        The company-wide list is resolved with an access-checked ``search``,
        so a user who cannot see a child contact does not learn it exists.
        """
        if scope != 'commercial':
            return [partner.id]
        commercial = partner.commercial_partner_id or partner
        partners = self.env['res.partner'].with_context(active_test=False).search(
            [('commercial_partner_id', '=', commercial.id)]
        )
        return (partners | partner).ids

    # ------------------------------------------------------------------
    # Domain building
    # ------------------------------------------------------------------
    @api.model
    def _date_bounds(self, options):
        """(from, to) naive UTC datetimes for the requested range, or (None, None).

        Ranges are anchored on the *user's* timezone: "today" means today where
        the user is, not where the server is.
        """
        date_range = options['date_range']
        if date_range == 'all':
            return None, None

        tz = pytz.timezone(self.env.user.tz or 'UTC')
        now_local = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        today_local = now_local.date()

        if date_range == 'custom':
            start = fields.Date.to_date(options['date_from']) if options['date_from'] else None
            end = fields.Date.to_date(options['date_to']) if options['date_to'] else None
        elif date_range == 'today':
            start, end = today_local, today_local
        elif date_range == 'week':
            start, end = today_local - timedelta(days=today_local.weekday()), today_local
        elif date_range == 'month':
            start, end = today_local.replace(day=1), today_local
        elif date_range == 'year':
            start, end = today_local.replace(month=1, day=1), today_local
        else:
            return None, None

        def to_utc(date_value, end_of_day):
            if not date_value:
                return None
            local = tz.localize(datetime.combine(
                date_value, time.max if end_of_day else time.min))
            return local.astimezone(pytz.utc).replace(tzinfo=None)

        return to_utc(start, False), to_utc(end, True)

    @api.model
    def _metadata_attachment_ids(self, options):
        """Attachment ids matching the metadata filters, or None if unfiltered.

        Returning ``None`` (no metadata filter) and returning ``[]`` (filter
        active but nothing matches) are deliberately different: the second one
        must produce an empty result, not an unfiltered one.
        """
        domain = []
        if options['important_only']:
            domain.append(('is_important', '=', True))
        if options['category_id']:
            domain.append(('category_id', '=', options['category_id']))
        if not domain:
            return None
        metadata = self.env['partner.document.metadata'].search(domain)
        return metadata.attachment_id.ids

    @api.model
    def _source_attachment_domain(self, source, partner_ids, options, base_domain):
        """Domain returning the attachments of one source for one partner set."""
        Model = self.env[source['model']]
        record_domain = Domain(
            self.env['partner.document.source']._get_source_record_domain(source, partner_ids)
        )
        # _search() applies the source model's own record rules and multi-company
        # rules; it stays a sub-select, nothing is materialised in Python.
        record_query = Model._search(record_domain)

        domain = base_domain & Domain('res_model', '=', source['model'])
        term = options['search']
        if not term:
            return domain & Domain('res_id', 'in', record_query)

        # Search hits either the attachment itself or the reference of the
        # record it hangs on ("INV/2026/0048"), both server-side.
        text_match = Domain('name', 'ilike', term) | Domain('description', 'ilike', term)
        matched = Domain('res_id', 'in', record_query) & text_match
        rec_name = Model._rec_name
        rec_field = Model._fields.get(rec_name) if rec_name else None
        if rec_field is not None and rec_field.store and rec_field.type in ('char', 'text'):
            named_query = Model._search(record_domain & Domain(rec_name, 'ilike', term))
            matched |= Domain('res_id', 'in', named_query)
        return domain & matched

    @api.model
    def _base_attachment_domain(self, options):
        # res_field must be pinned explicitly: ir.attachment only adds it
        # automatically when the domain mentions neither `id` nor `res_field`,
        # and the metadata filter below adds an `id` condition. Without it,
        # binary-field attachments (avatars, report caches) would leak in.
        domain = Domain('res_field', '=', False)

        date_from, date_to = self._date_bounds(options)
        if date_from:
            domain &= Domain('create_date', '>=', date_from)
        if date_to:
            domain &= Domain('create_date', '<=', date_to)

        metadata_ids = self._metadata_attachment_ids(options)
        if metadata_ids is not None:
            domain &= Domain('id', 'in', metadata_ids)
        return domain

    # ------------------------------------------------------------------
    # Live business documents
    # ------------------------------------------------------------------
    @api.model
    def _record_date_field(self, source):
        """The field a live document is dated by.

        ``create_date`` is the fallback because every model has it, so a
        provider that declares nothing still sorts and filters sensibly.
        """
        return source['date_field'] or 'create_date'

    @api.model
    def _live_document_domain(self, source, partner_ids, options):
        """Domain selecting the live documents of one source.

        Same shape as the attachment side: the partner link, then the date and
        the search term, all as SQL. ``search`` on the source model applies its
        own ACL and record rules, which is the entire security story for live
        documents - there is no second copy to protect.
        """
        Model = self.env[source['model']]
        domain = Domain(
            self.env['partner.document.source']._get_source_record_domain(source, partner_ids)
        )

        date_field = self._record_date_field(source)
        date_from, date_to = self._date_bounds(options)
        if date_from or date_to:
            # A declared date field may be null (an unposted invoice has no
            # invoice_date yet); fall back to create_date for those rows so a
            # date filter never silently swallows them.
            bounds = Domain.TRUE
            if date_from:
                bounds &= Domain(date_field, '>=', date_from)
            if date_to:
                bounds &= Domain(date_field, '<=', date_to)
            if date_field != 'create_date':
                fallback = Domain(date_field, '=', False)
                if date_from:
                    fallback &= Domain('create_date', '>=', date_from)
                if date_to:
                    fallback &= Domain('create_date', '<=', date_to)
                bounds |= fallback
            domain &= bounds

        term = options['search']
        if term:
            text = Domain(Model._rec_name, 'ilike', term) if source['rec_name_field'] else None
            if text is None:
                # Nothing sensible to match on: the source cannot answer a
                # text search, so it contributes nothing rather than everything.
                return Domain.FALSE
            domain &= text
        return domain

    @api.model
    def _fetch_live_document_rows(self, source, partner_ids, options):
        """Sort keys for the live documents of one source. No report is rendered."""
        Model = self.env[source['model']]
        domain = self._live_document_domain(source, partner_ids, options)
        if domain.is_false():
            return [], False

        date_field = self._record_date_field(source)
        fields_to_fetch = ['display_name', 'create_date', date_field]
        records = Model.search_fetch(
            domain, list(dict.fromkeys(fields_to_fetch)),
            limit=self._MAX_SCAN, order='id desc',
        )
        rows = []
        for record in records:
            rows.append({
                'kind': 'record',
                'key': ('record', source['model'], record.id),
                'id': False,
                'record_id': record.id,
                'name': record.display_name or '',
                'mimetype': '',
                'file_size': 0,
                'file_type': 'record',
                'create_date': self._as_datetime(record[date_field]) or record.create_date,
                'source': source,
            })
        return rows, len(records) >= self._MAX_SCAN

    @api.model
    def _as_datetime(self, value):
        """Normalise a Date or Datetime field value so both kinds sort together."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.combine(value, time.min)

    # ------------------------------------------------------------------
    # File typing
    # ------------------------------------------------------------------
    @api.model
    def _file_type(self, mimetype, name):
        """Classify a file: mimetype first, extension only as a fallback."""
        mimetype = (mimetype or '').split(';')[0].strip().lower()
        if mimetype not in AMBIGUOUS_MIMETYPES:
            if mimetype.startswith('image/'):
                return 'image'
            known = MIMETYPE_FILE_TYPES.get(mimetype)
            if known:
                return known
        extension = (name or '').rsplit('.', 1)
        if len(extension) == 2:
            return EXTENSION_FILE_TYPES.get(extension[1].lower(), 'other')
        return 'other'

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    @api.private
    @api.model
    def fetch_documents(self, partner, options):
        """Return one page of documents plus the counters the header needs.

        ``partner`` is an already access-checked ``res.partner`` recordset;
        the RPC surface is ``res.partner.action_fetch_documents``.
        """
        options = self._sanitise_options(options)
        partner_ids = self._resolve_partner_ids(partner, options['scope'])
        all_sources = self.env['partner.document.source']._get_available_sources()
        base_domain = self._base_attachment_domain(options)

        # `source` and `doc_kind` filter the *list*; the counters always
        # describe every source and both kinds, so the chips can show how much
        # is hiding behind each one.
        rows = []
        source_counts = defaultdict(int)
        truncated = False

        # Category and "important" live on ir.attachment metadata, so a live
        # business record can never satisfy them. Skipping the record queries
        # when one is active is both correct and cheaper.
        metadata_filtered = bool(options['important_only'] or options['category_id'])

        for source in all_sources:
            domain = self._source_attachment_domain(source, partner_ids, options, base_domain)
            attachments = self.env['ir.attachment'].search_fetch(
                domain, ['name', 'mimetype', 'file_size', 'create_date', 'res_id'],
                limit=self._MAX_SCAN, order='create_date desc, id desc',
            )
            if len(attachments) >= self._MAX_SCAN:
                truncated = True
            for attachment in attachments:
                rows.append({
                    'kind': 'attachment',
                    'key': ('attachment', attachment.id),
                    'id': attachment.id,
                    'record_id': attachment.res_id,
                    'name': attachment.name or '',
                    'mimetype': attachment.mimetype or '',
                    'file_size': attachment.file_size or 0,
                    'create_date': attachment.create_date,
                    'source': source,
                })

            if source['document_record'] and not metadata_filtered:
                record_rows, record_truncated = self._fetch_live_document_rows(
                    source, partner_ids, options)
                rows.extend(record_rows)
                truncated = truncated or record_truncated

        # Deduplicate on identity: the physical attachment id, or the
        # (model, id) of the business record. An attachment carries a single
        # res_model so overlap only happens if two bridge modules claim the
        # same model; lowest source sequence wins, deterministically.
        unique = {}
        for row in rows:
            existing = unique.get(row['key'])
            if existing is None or row['source']['sequence'] < existing['source']['sequence']:
                unique[row['key']] = row
        rows = list(unique.values())

        for row in rows:
            if row['kind'] == 'attachment':
                row['file_type'] = self._file_type(row['mimetype'], row['name'])
            source_counts[row['source']['code']] += 1

        kpi = self._compute_kpi(rows)

        selected = self._filter_rows(rows, options)
        selected = self._sort_rows(selected, options['order'])
        total = len(selected)
        page = selected[options['offset']:options['offset'] + options['limit']]

        return {
            'documents': self._render_page(page, partner),
            'total': total,
            'offset': options['offset'],
            'limit': options['limit'],
            'kpi': kpi,
            'sources': self._render_sources(all_sources, source_counts),
            'categories': self._render_categories(),
            'scope': options['scope'],
            'doc_kind': options['doc_kind'],
            'scope_available': bool(self._scope_sibling_count(partner)),
            'truncated': truncated,
        }

    @api.model
    def _render_page(self, page, partner):
        """Render one mixed page, batching each kind separately."""
        rendered = {}
        rendered.update(self._render_documents(
            [row for row in page if row['kind'] == 'attachment'], partner))
        rendered.update(self._render_live_documents(
            [row for row in page if row['kind'] == 'record'], partner))
        # Restore the page order the sort decided on.
        return [rendered[row['key']] for row in page if row['key'] in rendered]

    @api.model
    def _filter_rows(self, rows, options):
        """Apply the facets that are not expressible as a single SQL domain.

        Source, kind and file type land here because the KPI header and the
        source chips must keep counting the whole set while one of them is
        selected, and because the set spans two different tables. The rows are
        already restricted to this partner and already access-checked, so this
        is not a full-table scan in Python.
        """
        source_filter = options['source']
        file_type = options['file_type']
        doc_kind = options['doc_kind']
        if source_filter and source_filter != 'all':
            if source_filter.startswith('src:'):
                code = source_filter[4:]
                rows = [r for r in rows if r['source']['code'] == code]
            else:
                rows = [r for r in rows if r['source']['group'] == source_filter]
        if doc_kind != 'all':
            rows = [r for r in rows if r['kind'] == doc_kind]
        if file_type != 'all':
            # A live business record is not a file and has no file type, so
            # picking one narrows the list to stored files by definition.
            rows = [r for r in rows if r['kind'] == 'attachment' and r['file_type'] == file_type]
        return rows

    @api.model
    def _sort_rows(self, rows, order):
        epoch = datetime(1970, 1, 1)
        # `key` is the identity tuple: ('attachment', id) or ('record', model,
        # id). It is totally ordered across both kinds, which makes every sort
        # below deterministic even when two items share a date or a name.
        keys = {
            'date_desc': (lambda r: (r['create_date'] or epoch, r['key']), True),
            'date_asc': (lambda r: (r['create_date'] or epoch, r['key']), False),
            'name_asc': (lambda r: (r['name'].lower(), r['key']), False),
            'name_desc': (lambda r: (r['name'].lower(), r['key']), True),
            'size_desc': (lambda r: (r['file_size'], r['key']), True),
            'size_asc': (lambda r: (r['file_size'], r['key']), False),
            'source': (lambda r: (r['source']['sequence'], r['source']['code']), False),
        }
        key, reverse = keys.get(order, keys['date_desc'])
        if order == 'source':
            # Stable two-level sort: newest first inside each source.
            rows = sorted(rows, key=lambda r: (r['create_date'] or epoch, r['key']), reverse=True)
        return sorted(rows, key=key, reverse=reverse)

    @api.model
    def _compute_kpi(self, rows):
        kpi = {
            'total': len(rows),
            'record': 0, 'attachment': 0,
            'pdf': 0, 'image': 0, 'document': 0, 'other': 0,
            'size': 0, 'latest_date': False,
        }
        latest = None
        for row in rows:
            if row['create_date'] and (latest is None or row['create_date'] > latest):
                latest = row['create_date']
            if row['kind'] == 'record':
                kpi['record'] += 1
                continue
            kpi['attachment'] += 1
            file_type = row['file_type']
            if file_type == 'pdf':
                kpi['pdf'] += 1
            elif file_type == 'image':
                kpi['image'] += 1
            elif file_type in DOCUMENT_FILE_TYPES:
                kpi['document'] += 1
            else:
                kpi['other'] += 1
            kpi['size'] += row['file_size'] or 0
            if row['create_date'] and (latest is None or row['create_date'] > latest):
                latest = row['create_date']
        kpi['latest_date'] = fields.Datetime.to_string(latest) if latest else False
        return kpi

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    @api.model
    def _render_documents(self, page, partner):
        """Turn the page rows into the normalised dicts the client consumes.

        Everything still missing at this point (author, source reference,
        permissions, metadata) is read in batch for the page only - never per
        document, and never including the binary payload.
        """
        if not page:
            return {}
        attachments = self.env['ir.attachment'].browse([row['id'] for row in page])
        attachments.fetch(['res_id', 'create_uid', 'checksum', 'type', 'url', 'description'])

        writable = set(attachments._filtered_access('write')._ids)
        removable = set(attachments._filtered_access('unlink')._ids)

        metadata_by_attachment = {
            metadata.attachment_id.id: metadata
            for metadata in self.env['partner.document.metadata'].search(
                [('attachment_id', 'in', attachments.ids)]
            )
        }
        source_names = self._source_display_names(page, attachments)

        documents = {}
        for row in page:
            attachment = attachments.browse(row['id'])
            source = row['source']
            metadata = metadata_by_attachment.get(attachment.id)
            source_id = attachment.res_id
            is_self = source['model'] == 'res.partner' and source_id == partner.id
            documents[row['key']] = {
                'kind': 'attachment',
                'item_id': 'attachment-%s' % attachment.id,
                # Groups a file under the live document it hangs on.
                'group_key': '%s,%s' % (source['model'], source_id or 0),
                'attachment_id': attachment.id,
                'name': row['name'],
                'mimetype': row['mimetype'],
                'file_size': row['file_size'],
                'file_type': row['file_type'],
                'create_date': fields.Datetime.to_string(row['create_date']),
                'checksum': attachment.checksum or '',
                'type': attachment.type,
                'url': attachment.url if attachment.type == 'url' else '',
                'description': attachment.description or '',
                'source_code': source['code'],
                'source_model': source['model'],
                'source_group': source['group'],
                'source_record_id': source_id,
                'source_label': source_names['labels'].get(attachment.id, source['label']),
                'source_display_name': source_names['names'].get(attachment.id, ''),
                'partner_id': partner.id,
                'uploaded_by': attachment.create_uid.display_name if attachment.create_uid else '',
                'category_id': metadata.category_id.id if metadata and metadata.category_id else False,
                'category_name': metadata.category_id.name if metadata and metadata.category_id else '',
                'is_important': bool(metadata and metadata.is_important),
                'can_download': True,
                'can_open_source': bool(source_id) and not is_self,
                'can_write': attachment.id in writable,
                # Mirrors what action_delete will actually allow, so the flag
                # never promises a button that the server would then refuse.
                'can_delete': (
                    attachment.id in removable
                    and attachment.res_model == 'res.partner'
                ),
                'can_print': False,
                'report_name': '',
            }
        return documents

    @api.model
    def _render_live_documents(self, page, partner):
        """Turn live-document rows into cards, read straight off the records.

        Nothing here is stored or cached: every value on the card is read from
        the business record during this request, which is what makes the card
        follow the record's reference, state, amount, currency and partner
        without any synchronisation step. No report is rendered - printing is
        a separate, explicit action.
        """
        if not page:
            return {}

        by_model = defaultdict(list)
        for row in page:
            by_model[row['source']['model']].append(row)

        documents = {}
        for model_name, rows in by_model.items():
            source = rows[0]['source']
            Model = self.env[model_name]
            record_ids = [row['record_id'] for row in rows]
            # These records came back from an access-checked search, but one
            # may have been deleted since; exists() keeps a stale page honest.
            records = Model.browse(record_ids).exists()
            available = {record.id: record for record in records}

            summary_fields = [
                field for field in (
                    source['date_field'], source['state_field'],
                    source['amount_field'], source['currency_field'],
                    source['subtype_field'],
                ) if field
            ]
            records.fetch(list(dict.fromkeys(
                ['display_name', 'create_date', 'write_date'] + summary_fields)))

            state_labels = self._selection_labels(Model, source['state_field'])
            report = self.env['partner.document.source']._get_source_report(source)
            attachment_counts = self._related_attachment_counts(model_name, records.ids)

            for row in rows:
                record = available.get(row['record_id'])
                if record is None:
                    continue
                values = {
                    'kind': 'record',
                    'item_id': 'record-%s-%s' % (model_name, record.id),
                    'group_key': '%s,%s' % (model_name, record.id),
                    'attachment_id': False,
                    'name': record.display_name or '',
                    'mimetype': '',
                    'file_size': 0,
                    'file_type': 'record',
                    'create_date': fields.Datetime.to_string(row['create_date']),
                    'write_date': fields.Datetime.to_string(record.write_date),
                    'checksum': '',
                    'type': 'record',
                    'url': '',
                    'description': '',
                    'source_code': source['code'],
                    'source_model': model_name,
                    'source_group': source['group'],
                    'source_record_id': record.id,
                    'source_label': self._record_type_label(source, record),
                    'source_display_name': record.display_name or '',
                    'partner_id': partner.id,
                    'uploaded_by': '',
                    'state': record[source['state_field']] if source['state_field'] else False,
                    'state_label': self._state_label(record, source, state_labels),
                    'amount': record[source['amount_field']] if source['amount_field'] else False,
                    'amount_label': self._amount_label(record, source),
                    'currency_name': (
                        record[source['currency_field']].name
                        if source['currency_field'] and record[source['currency_field']] else ''
                    ),
                    'attachment_count': attachment_counts.get(record.id, 0),
                    'category_id': False,
                    'category_name': '',
                    'is_important': False,
                    # A live document has no file to download and no metadata
                    # of its own; it is a window onto the record.
                    'can_download': False,
                    'can_open_source': True,
                    'can_write': False,
                    'can_delete': False,
                    'can_print': bool(report),
                    'report_name': report.report_name if report else '',
                }
                documents[row['key']] = self.env['partner.document.source'] \
                    ._prepare_live_document_values(source, record, values)
        return documents

    @api.model
    def _record_type_label(self, source, record):
        """"Customer Invoice" rather than "account.move", subtype-aware."""
        label = source['label']
        subtype_field = source['subtype_field']
        if subtype_field:
            return source['subtype_labels'].get(record[subtype_field], label)
        return label

    @api.model
    def _selection_labels(self, Model, field_name):
        """Translated {value: label} for a selection field, once per model."""
        if not field_name or Model._fields[field_name].type != 'selection':
            return {}
        description = Model.fields_get([field_name], ['selection'])
        return dict(description[field_name].get('selection') or [])

    @api.model
    def _state_label(self, record, source, state_labels):
        field_name = source['state_field']
        if not field_name:
            return ''
        value = record[field_name]
        if not value:
            return ''
        field = record._fields[field_name]
        if field.type == 'many2one':
            return value.display_name or ''
        return state_labels.get(value, value)

    @api.model
    def _amount_label(self, record, source):
        """Formatted total, in the record's own currency and the user's locale."""
        field_name = source['amount_field']
        if not field_name:
            return ''
        amount = record[field_name]
        if not amount:
            return ''
        currency = record[source['currency_field']] if source['currency_field'] else None
        return formatLang(self.env, amount, currency_obj=currency or None)

    @api.model
    def _related_attachment_counts(self, model_name, record_ids):
        """How many files hang on each of the page's live documents.

        One access-checked grouped query per model on the page - the res_model
        is pinned, so it takes the same fast path as the list itself.
        """
        if not record_ids:
            return {}
        groups = self.env['ir.attachment']._read_group(
            [('res_model', '=', model_name),
             ('res_id', 'in', record_ids),
             ('res_field', '=', False)],
            groupby=['res_id'],
            aggregates=['__count'],
        )
        return {res_id: count for res_id, count in groups}

    @api.model
    def _source_display_names(self, page, attachments):
        """Batch-resolve "Customer Invoice INV/2026/0048" for the page.

        One query per distinct model, plus one for the subtype field when the
        source declares one. Never one query per document.
        """
        names, labels = {}, {}
        by_model = defaultdict(list)
        for row in page:
            attachment = attachments.browse(row['id'])
            if attachment.res_id:
                by_model[row['source']['model']].append((attachment.id, attachment.res_id, row['source']))

        for model_name, entries in by_model.items():
            source = entries[0][2]
            record_ids = list({entry[1] for entry in entries})
            # These records are readable by construction (the attachment search
            # only returns attachments whose record the user may read), but a
            # record deleted between the two queries would raise, so filter.
            records = self.env[model_name].browse(record_ids).exists()._filtered_access('read')
            fields_to_read = ['display_name']
            subtype_field = source['subtype_field']
            if subtype_field:
                fields_to_read.append(subtype_field)
            records.fetch(fields_to_read)
            by_id = {record.id: record for record in records}
            for attachment_id, res_id, _source in entries:
                record = by_id.get(res_id)
                if record is None:
                    continue
                names[attachment_id] = record.display_name or ''
                label = source['label']
                if subtype_field:
                    label = source['subtype_labels'].get(record[subtype_field], label)
                labels[attachment_id] = label
        return {'names': names, 'labels': labels}

    @api.model
    def _render_sources(self, sources, counts):
        group_labels = self.env['partner.document.source']._get_group_labels()
        groups, seen = [], {}
        for source in sources:
            count = counts.get(source['code'], 0)
            group = source['group']
            if group not in seen:
                seen[group] = {
                    'group': group,
                    'label': group_labels.get(group, group),
                    'count': 0,
                    'sources': [],
                }
                groups.append(seen[group])
            seen[group]['count'] += count
            seen[group]['sources'].append({
                'code': source['code'],
                'model': source['model'],
                'label': source['label'],
                'count': count,
            })
        # Only surface buckets that can actually hold something for this
        # partner: an empty "CRM" chip on a database without leads is noise.
        return [group for group in groups if group['count']]

    @api.model
    def _render_categories(self):
        return [
            {'id': category.id, 'name': category.name, 'color': category.color}
            for category in self.env['partner.document.category'].search([])
        ]

    @api.model
    def _scope_sibling_count(self, partner):
        """How many other contacts share this partner's commercial entity."""
        commercial = partner.commercial_partner_id or partner
        return self.env['res.partner'].with_context(active_test=False).search_count([
            ('commercial_partner_id', '=', commercial.id),
            ('id', '!=', partner.id),
        ])

    # ------------------------------------------------------------------
    # Cheap count, for the smart button
    # ------------------------------------------------------------------
    @api.private
    @api.model
    def count_documents(self, partner, scope='self'):
        """Total accessible documents - files and live records - as COUNT(*) only.

        The registry guarantees one source per model, and an attachment
        carries exactly one ``res_model``, so summing per-source counts cannot
        double-count. No report is rendered and no card is built.
        """
        scope = scope if scope in VALID_SCOPES else 'self'
        partner_ids = self._resolve_partner_ids(partner, scope)
        base_domain = Domain('res_field', '=', False)
        options = self._sanitise_options({})
        total = 0
        for source in self.env['partner.document.source']._get_available_sources():
            domain = self._source_attachment_domain(source, partner_ids, options, base_domain)
            total += self.env['ir.attachment'].search_count(domain)
            if source['document_record']:
                record_domain = self._live_document_domain(source, partner_ids, options)
                if not record_domain.is_false():
                    total += self.env[source['model']].search_count(record_domain)
        return total

    # ------------------------------------------------------------------
    # Actions on a single document
    # ------------------------------------------------------------------
    @api.model
    def _get_document(self, attachment_id):
        """Browse an attachment, enforcing read access.

        Client-supplied ids are never trusted: this is the single funnel every
        per-document action goes through.
        """
        try:
            attachment_id = int(attachment_id)
        except (TypeError, ValueError):
            raise UserError(_("Invalid document reference."))
        attachment = self.env['ir.attachment'].browse(attachment_id).exists()
        if not attachment:
            raise UserError(_("This document no longer exists."))
        attachment.check_access('read')
        return attachment

    @api.model
    def action_open_source(self, attachment_id):
        """Return an act_window opening the record the document hangs on."""
        attachment = self._get_document(attachment_id)
        model_name, res_id = attachment.res_model, attachment.res_id
        if not model_name or not res_id:
            raise UserError(_("This document is not linked to any record."))
        # Only models the Document Center actually aggregates can be opened,
        # so this cannot be turned into a generic "open any record" endpoint.
        allowed = {
            source['model']
            for source in self.env['partner.document.source']._get_available_sources()
        }
        if model_name not in allowed:
            raise UserError(_("This document's record cannot be opened from here."))
        record = self.env[model_name].browse(res_id).exists()
        if not record:
            raise UserError(_("The record this document belongs to no longer exists."))
        record.check_access('read')
        return {
            'type': 'ir.actions.act_window',
            'res_model': model_name,
            'res_id': record.id,
            'views': [(False, 'form')],
            'target': 'current',
        }

    @api.model
    def _get_live_document(self, model_name, res_id):
        """Browse a business record as a live document, enforcing read access.

        The model must be a registered source that publishes live documents,
        so this cannot be used as a generic "read any record" endpoint, and
        the record must pass its own ACL and record rules.
        """
        source = next(
            (s for s in self.env['partner.document.source']._get_available_sources()
             if s['model'] == model_name and s['document_record']),
            None,
        )
        if not source:
            raise UserError(_("This kind of record is not a Document Center document."))
        try:
            res_id = int(res_id)
        except (TypeError, ValueError):
            raise UserError(_("Invalid document reference."))
        record = self.env[model_name].browse(res_id).exists()
        if not record:
            raise UserError(_("This document no longer exists."))
        record.check_access('read')
        return source, record

    @api.model
    def action_open_live_document(self, model_name, res_id):
        """Open the business record a live document stands for."""
        _source, record = self._get_live_document(model_name, res_id)
        return {
            'type': 'ir.actions.act_window',
            'res_model': record._name,
            'res_id': record.id,
            'views': [(False, 'form')],
            'target': 'current',
        }

    @api.model
    def action_print_live_document(self, model_name, res_id):
        """Render the source's report from the record as it stands right now.

        Nothing is stored: the action goes back through Odoo's own report
        machinery every time, so a printed document always reflects the
        current values rather than a snapshot taken when the card was drawn.
        """
        source, record = self._get_live_document(model_name, res_id)
        report = self.env['partner.document.source']._get_source_report(source)
        if not report:
            raise UserError(_("No printable report is configured for this document."))
        return report.report_action(record)

    @api.model
    def action_set_metadata(self, attachment_id, values):
        """Set the category / important flag, gated on write access."""
        attachment = self._get_document(attachment_id)
        attachment.check_access('write')
        payload = {}
        if 'is_important' in values:
            payload['is_important'] = bool(values['is_important'])
        if 'category_id' in values:
            category_id = values['category_id']
            if category_id:
                category = self.env['partner.document.category'].browse(int(category_id)).exists()
                if not category:
                    raise UserError(_("Unknown document category."))
                payload['category_id'] = category.id
            else:
                payload['category_id'] = False
        if not payload:
            return False
        metadata = self.env['partner.document.metadata']._get_or_create(attachment)
        metadata.write(payload)
        return True

    @api.model
    def action_rename(self, attachment_id, name):
        attachment = self._get_document(attachment_id)
        name = (name or '').strip()
        if not name:
            raise UserError(_("A document name cannot be empty."))
        # write() on ir.attachment re-runs the cascade check itself.
        attachment.write({'name': name})
        return True

    @api.model
    def action_delete(self, attachment_id):
        """Delete a document, only where Odoo would allow it anyway.

        Restricted to files that live directly on the contact: an invoice's
        attachment is part of that invoice's audit trail and is not something
        the Document Center should offer to remove.
        """
        attachment = self._get_document(attachment_id)
        if attachment.res_model != 'res.partner':
            raise UserError(_(
                "Only files attached directly to the contact can be deleted here. "
                "Open the source document to manage its own attachments."
            ))
        if not attachment.has_access('unlink'):
            raise AccessError(_("You are not allowed to delete this document."))
        attachment.unlink()
        return True
