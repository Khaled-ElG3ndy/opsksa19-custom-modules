# -*- coding: utf-8 -*-
"""Live business documents.

A live document is not a stored thing: it is the business record, read at
request time. These tests exist to pin that down - that a record shows up with
no attachment behind it, that every edit is visible on the next read with no
synchronisation step, that it follows its partner, that it vanishes with the
record, and that it never weakens the access rules or drags report rendering
into the listing path.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.tools import formatLang


@tagged('post_install', '-at_install')
class TestLiveDocuments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref('base.main_company')
        cls.Attachment = cls.env['ir.attachment']
        cls.Center = cls.env['partner.document.center']
        cls.Source = cls.env['partner.document.source']

        cls.customer = cls.env['res.partner'].create({
            'name': 'Live Docs Customer', 'is_company': True, 'company_id': False,
        })
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Live Docs Other Customer', 'is_company': True, 'company_id': False,
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _fetch(self, partner, user=None, **options):
        partner = partner.with_user(user) if user else partner
        return partner.action_fetch_documents(options)

    def _names(self, result):
        return sorted(document['name'] for document in result['documents'])

    def _live(self, result, model=None):
        return [
            document for document in result['documents']
            if document['kind'] == 'record'
            and (model is None or document['source_model'] == model)
        ]

    def _order(self, partner=None):
        """A purchase order: installed here, and trivial to create."""
        if 'purchase.order' not in self.env:
            self.skipTest("purchase is not installed")
        return self.env['purchase.order'].create({
            'partner_id': (partner or self.customer).id,
        })

    def _attach(self, name, model, res_id, mimetype=None):
        return self.Attachment.create({
            'name': name, 'raw': b'live-doc-test',
            'res_model': model, 'res_id': res_id, 'mimetype': mimetype,
        })

    # ------------------------------------------------------------------
    # 1. a business record is a document, with or without files
    # ------------------------------------------------------------------
    def test_record_appears_without_any_attachment(self):
        order = self._order()
        result = self._fetch(self.customer)

        live = self._live(result, 'purchase.order')
        self.assertEqual(len(live), 1, "the purchase order did not appear on its own")
        document = live[0]
        self.assertEqual(document['name'], order.display_name)
        self.assertEqual(document['source_record_id'], order.id)
        self.assertFalse(document['attachment_id'], "a live document is not an attachment")
        self.assertEqual(document['attachment_count'], 0)
        self.assertTrue(document['can_open_source'])
        self.assertFalse(document['can_download'], "there is no stored file to download")

    def test_invoice_appears_without_any_attachment(self):
        if 'account.move' not in self.env:
            self.skipTest("account is not installed")
        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', self.company.id)], limit=1)
        if not journal:
            self.skipTest("no sale journal configured")
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.customer.id,
            'journal_id': journal.id,
        })

        live = self._live(self._fetch(self.customer), 'account.move')
        self.assertEqual(len(live), 1)
        # The user sees the document type, never the technical model.
        self.assertEqual(live[0]['source_label'], 'Customer Invoice')
        self.assertEqual(live[0]['source_record_id'], invoice.id)

    def test_no_attachment_is_created_to_make_a_record_appear(self):
        order = self._order()
        self._fetch(self.customer)
        self.assertFalse(
            self.Attachment.search([('res_model', '=', 'purchase.order'),
                                    ('res_id', '=', order.id)]),
            "listing a live document created a stored file",
        )

    # ------------------------------------------------------------------
    # 2. the record is the single source of truth
    # ------------------------------------------------------------------
    def test_edits_are_visible_on_the_next_read(self):
        order = self._order()
        before = self._live(self._fetch(self.customer), 'purchase.order')[0]
        self.assertEqual(before['name'], order.display_name)

        order.write({'name': 'PO-RENAMED-0001'})
        after = self._live(self._fetch(self.customer), 'purchase.order')[0]
        self.assertEqual(after['name'], 'PO-RENAMED-0001',
                         "the live document did not follow the record's reference")
        self.assertEqual(after['source_display_name'], 'PO-RENAMED-0001')

    def test_amount_follows_the_record(self):
        order = self._order()
        product = self.env['product.product'].search([('purchase_ok', '=', True)], limit=1)
        if not product:
            self.skipTest("no purchasable product available")
        line = self.env['purchase.order.line'].create({
            'order_id': order.id,
            'product_id': product.id,
            'product_qty': 3,
            'price_unit': 100.0,
        })

        def expected():
            return formatLang(self.env, order.amount_total, currency_obj=order.currency_id)

        first = self._live(self._fetch(self.customer), 'purchase.order')[0]
        self.assertEqual(first['amount_label'], expected(),
                         "the live document did not read the current total")

        line.write({'price_unit': 250.0})
        second = self._live(self._fetch(self.customer), 'purchase.order')[0]
        self.assertEqual(second['amount_label'], expected())
        self.assertNotEqual(second['amount_label'], first['amount_label'],
                            "the amount did not follow the record")

    def test_state_follows_the_record(self):
        order = self._order()
        before = self._live(self._fetch(self.customer), 'purchase.order')[0]
        self.assertEqual(before['state'], 'draft')
        self.assertTrue(before['state_label'])

        order.write({'state': 'purchase'})

        after = self._live(self._fetch(self.customer), 'purchase.order')[0]
        self.assertEqual(after['state'], 'purchase')
        self.assertNotEqual(after['state_label'], before['state_label'],
                            "the status badge did not follow the record's state")

    def test_no_business_field_is_copied_anywhere(self):
        """Nothing in this module stores what a live document displays."""
        order = self._order()
        self._fetch(self.customer)
        stored = self.env['partner.document.metadata'].search([])
        self.assertFalse(
            stored.filtered(lambda m: not m.attachment_id),
            "a live document left a stored row behind",
        )
        self.assertFalse(
            self.Attachment.search([('res_model', '=', 'purchase.order'),
                                    ('res_id', '=', order.id)]),
        )

    # ------------------------------------------------------------------
    # 3. the document follows the partner
    # ------------------------------------------------------------------
    def test_changing_partner_moves_the_document(self):
        order = self._order()
        self.assertEqual(len(self._live(self._fetch(self.customer), 'purchase.order')), 1)
        self.assertEqual(len(self._live(self._fetch(self.other_customer), 'purchase.order')), 0)

        order.write({'partner_id': self.other_customer.id})

        self.assertEqual(
            len(self._live(self._fetch(self.customer), 'purchase.order')), 0,
            "the live document stayed with the previous partner",
        )
        moved = self._live(self._fetch(self.other_customer), 'purchase.order')
        self.assertEqual(len(moved), 1, "the live document did not follow the new partner")
        self.assertEqual(moved[0]['source_record_id'], order.id)

    # ------------------------------------------------------------------
    # 4. the document dies with the record
    # ------------------------------------------------------------------
    def test_deleting_the_record_removes_the_live_document(self):
        order = self._order()
        self.assertEqual(len(self._live(self._fetch(self.customer), 'purchase.order')), 1)

        # purchase refuses to delete a live order; cancel first, as a user would.
        order.button_cancel()
        order.unlink()

        result = self._fetch(self.customer)
        self.assertEqual(len(self._live(result, 'purchase.order')), 0)
        self.assertEqual(result['total'], 0)

    # ------------------------------------------------------------------
    # 5. live documents and files coexist
    # ------------------------------------------------------------------
    def test_live_document_and_its_attachments_coexist(self):
        order = self._order()
        self._attach('scan.pdf', 'purchase.order', order.id, 'application/pdf')
        self._attach('email.pdf', 'purchase.order', order.id, 'application/pdf')

        result = self._fetch(self.customer)
        kinds = [document['kind'] for document in result['documents']]
        self.assertEqual(result['total'], 3, "expected one record plus two files")
        self.assertEqual(kinds.count('record'), 1)
        self.assertEqual(kinds.count('attachment'), 2)

        live = self._live(result, 'purchase.order')[0]
        self.assertEqual(live['attachment_count'], 2)

        # Both kinds carry the same group key, which is what lets the client
        # nest the files under the document they belong to.
        keys = {document['group_key'] for document in result['documents']}
        self.assertEqual(keys, {'purchase.order,%s' % order.id})

        self.assertEqual(result['kpi']['record'], 1)
        self.assertEqual(result['kpi']['attachment'], 2)
        self.assertEqual(result['kpi']['total'], 3)

    def test_doc_kind_filter(self):
        order = self._order()
        self._attach('scan.pdf', 'purchase.order', order.id)

        everything = self._fetch(self.customer, doc_kind='all')
        self.assertEqual(everything['total'], 2)

        records = self._fetch(self.customer, doc_kind='record')
        self.assertEqual(records['total'], 1)
        self.assertEqual(records['documents'][0]['kind'], 'record')
        # The counters keep describing the whole set while a kind is selected.
        self.assertEqual(records['kpi']['total'], 2)

        files = self._fetch(self.customer, doc_kind='attachment')
        self.assertEqual(files['total'], 1)
        self.assertEqual(files['documents'][0]['name'], 'scan.pdf')

    def test_file_type_facet_narrows_to_files(self):
        order = self._order()
        self._attach('scan.pdf', 'purchase.order', order.id, 'application/pdf')
        result = self._fetch(self.customer, file_type='pdf')
        self.assertEqual(self._names(result), ['scan.pdf'],
                         "a live document answered a file-type filter")

    def test_metadata_filters_exclude_live_documents(self):
        order = self._order()
        attachment = self._attach('scan.pdf', 'purchase.order', order.id)
        self.Center.action_set_metadata(attachment.id, {'is_important': True})

        result = self._fetch(self.customer, important_only=True)
        self.assertEqual(self._names(result), ['scan.pdf'])
        self.assertEqual(len(self._live(result)), 0)

    def test_count_includes_live_documents(self):
        order = self._order()
        self._attach('scan.pdf', 'purchase.order', order.id)
        self.assertEqual(
            self.customer.action_count_documents('self'),
            self._fetch(self.customer)['total'],
            "the smart button count drifted from the list",
        )

    def test_pagination_across_both_kinds(self):
        order = self._order()
        for index in range(5):
            self._attach('file-%02d.pdf' % index, 'purchase.order', order.id)

        first = self._fetch(self.customer, limit=2, offset=0)
        self.assertEqual(first['total'], 6)
        self.assertEqual(len(first['documents']), 2)

        seen = []
        for offset in (0, 2, 4):
            page = self._fetch(self.customer, limit=2, offset=offset)
            seen.extend(document['item_id'] for document in page['documents'])
        self.assertEqual(len(seen), 6)
        self.assertEqual(len(set(seen)), 6, "an item appeared on two pages")

    # ------------------------------------------------------------------
    # 6. historical attachments are snapshots and stay untouched
    # ------------------------------------------------------------------
    def test_historical_attachment_is_not_regenerated_when_the_record_changes(self):
        order = self._order()
        signed = self._attach('Signed PO.pdf', 'purchase.order', order.id, 'application/pdf')
        original = {
            'name': signed.name,
            'checksum': signed.checksum,
            'raw': signed.raw,
            'create_date': signed.create_date,
        }

        order.write({'name': 'PO-AMENDED-0002'})
        self.Center.invalidate_model()
        signed.invalidate_recordset()

        self.assertEqual(signed.name, original['name'])
        self.assertEqual(signed.checksum, original['checksum'])
        self.assertEqual(signed.raw, original['raw'])
        self.assertEqual(signed.create_date, original['create_date'])

        result = self._fetch(self.customer)
        live = self._live(result, 'purchase.order')[0]
        snapshot = next(d for d in result['documents'] if d['kind'] == 'attachment')
        self.assertEqual(live['name'], 'PO-AMENDED-0002', "the live view did not update")
        self.assertEqual(snapshot['name'], 'Signed PO.pdf', "the snapshot moved with the record")

    # ------------------------------------------------------------------
    # 7. security is unchanged
    # ------------------------------------------------------------------
    def test_live_documents_respect_model_access(self):
        order = self._order()
        self._attach('scan.pdf', 'purchase.order', order.id)

        basic = self.env['res.users'].create({
            'name': 'Live Docs Basic User',
            'login': 'pdc_live_basic',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        if self.env['purchase.order'].with_user(basic).browse().has_access('read'):
            self.skipTest("this database grants purchase.order read to plain users")

        result = self._fetch(self.customer, user=basic)
        self.assertEqual(result['total'], 0,
                         "the Document Center exposed records the user cannot read")

    def test_live_documents_respect_record_rules(self):
        """A record in another company must not surface as a live document."""
        other_company = self.env['res.company'].create({'name': 'Live Docs Company B'})
        contact_b = self.env['res.partner'].create({
            'name': 'Live Docs Contact B',
            'parent_id': self.customer.id,
            'company_id': other_company.id,
        })
        self._attach('company-b.pdf', 'res.partner', contact_b.id)

        restricted = self.env['res.users'].create({
            'name': 'Live Docs Company A User',
            'login': 'pdc_live_company_a',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('base.group_partner_manager').id,
            ])],
        })
        names = self._names(
            self._fetch(self.customer, user=restricted, scope='commercial'))
        self.assertNotIn('company-b.pdf', names)

    def test_open_and_print_reject_unregistered_models(self):
        view = self.env.ref('base.view_partner_form')
        with self.assertRaises(Exception):
            self.Center.action_open_live_document('ir.ui.view', view.id)
        with self.assertRaises(Exception):
            self.Center.action_print_live_document('ir.ui.view', view.id)

    def test_open_and_print_reject_records_out_of_reach(self):
        order = self._order()
        basic = self.env['res.users'].create({
            'name': 'Live Docs Reader',
            'login': 'pdc_live_reader',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        if self.env['purchase.order'].with_user(basic).browse().has_access('read'):
            self.skipTest("this database grants purchase.order read to plain users")
        Center = self.Center.with_user(basic)
        with self.assertRaises(Exception):
            Center.action_open_live_document('purchase.order', order.id)
        with self.assertRaises(Exception):
            Center.action_print_live_document('purchase.order', order.id)

    def test_open_live_document_returns_the_record(self):
        order = self._order()
        action = self.Center.action_open_live_document('purchase.order', order.id)
        self.assertEqual(action['res_model'], 'purchase.order')
        self.assertEqual(action['res_id'], order.id)

    def test_print_returns_a_report_action(self):
        order = self._order()
        source = next(
            s for s in self.Source._get_available_sources() if s['model'] == 'purchase.order')
        if not self.Source._get_source_report(source):
            self.skipTest("no purchase order report installed")
        action = self.Center.action_print_live_document('purchase.order', order.id)
        self.assertEqual(action['type'], 'ir.actions.report')

    # ------------------------------------------------------------------
    # Reports are never rendered while listing
    # ------------------------------------------------------------------
    def test_listing_never_renders_a_report(self):
        order = self._order()
        self._attach('scan.pdf', 'purchase.order', order.id)
        Report = type(self.env['ir.actions.report'])

        with patch.object(Report, '_render_qweb_pdf') as render_pdf, \
                patch.object(Report, '_render') as render:
            result = self._fetch(self.customer)
            self.customer.action_count_documents('self')

        self.assertTrue(result['documents'])
        render_pdf.assert_not_called()
        render.assert_not_called()

    # ------------------------------------------------------------------
    # 8. a future custom module can publish live documents
    # ------------------------------------------------------------------
    def test_custom_provider_can_publish_live_documents(self):
        """Registering a model the core has never heard of takes one dict.

        ``res.users`` stands in for a future ``hotel.contract`` here: it is a
        model the Document Center does not know, related to a partner by a real
        many2one, and it becomes a live document without touching the engine.
        """
        user = self.env['res.users'].create({
            'name': 'Live Docs Provider User',
            'login': 'pdc_live_provider',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        original = type(self.Source)._get_source_definitions

        def with_custom_source(source_self):
            return original(source_self) + [{
                'code': 'custom_live',
                'model': 'res.users',
                'partner_fields': ['partner_id'],
                'group': 'other',
                'label': 'Service Contract',
                'sequence': 900,
                'document_record': True,
                'state_field': 'active',
            }]

        with patch.object(type(self.Source), '_get_source_definitions', with_custom_source):
            result = self._fetch(user.partner_id)
            live = self._live(result, 'res.users')

        self.assertEqual(len(live), 1, "the custom provider published nothing")
        self.assertEqual(live[0]['source_label'], 'Service Contract')
        self.assertEqual(live[0]['source_record_id'], user.id)
        self.assertEqual(live[0]['source_group'], 'other')

    def test_custom_provider_can_enrich_its_cards(self):
        """The metadata hook runs without costing a query per card."""
        order = self._order()
        Source = type(self.Source)
        original = Source._prepare_live_document_values

        def enriched(source_self, source, record, values):
            values = original(source_self, source, record, values)
            if source['model'] == 'purchase.order':
                values['custom_note'] = 'from-provider-%s' % record.id
            return values

        with patch.object(Source, '_prepare_live_document_values', enriched):
            live = self._live(self._fetch(self.customer), 'purchase.order')[0]

        self.assertEqual(live['custom_note'], 'from-provider-%s' % order.id)

    def test_provider_can_opt_out_of_live_documents(self):
        order = self._order()
        Source = type(self.Source)
        original = Source._get_source_definitions

        def files_only(source_self):
            definitions = []
            for definition in original(source_self):
                definition = dict(definition)
                if definition.get('model') == 'purchase.order':
                    definition['document_record'] = False
                definitions.append(definition)
            return definitions

        self._attach('scan.pdf', 'purchase.order', order.id)
        with patch.object(Source, '_get_source_definitions', files_only):
            result = self._fetch(self.customer)

        self.assertEqual(self._names(result), ['scan.pdf'])
        self.assertEqual(len(self._live(result)), 0)

    def test_declared_summary_fields_are_validated(self):
        """A provider naming a field that does not exist loses that line only."""
        Source = type(self.Source)
        original = Source._get_source_definitions

        def bogus_fields(source_self):
            definitions = []
            for definition in original(source_self):
                definition = dict(definition)
                if definition.get('model') == 'purchase.order':
                    definition['amount_field'] = 'does_not_exist'
                    definition['state_field'] = 'also_missing'
                definitions.append(definition)
            return definitions

        self._order()
        with patch.object(Source, '_get_source_definitions', bogus_fields):
            live = self._live(self._fetch(self.customer), 'purchase.order')

        self.assertEqual(len(live), 1, "a bad summary field broke the whole source")
        self.assertEqual(live[0]['amount_label'], '')
        self.assertEqual(live[0]['state_label'], '')
