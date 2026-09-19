# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPartnerDocumentCenter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref('base.main_company')
        cls.Attachment = cls.env['ir.attachment']
        cls.Center = cls.env['partner.document.center']

        cls.parent = cls.env['res.partner'].create({
            'name': 'ABC Trading',
            'is_company': True,
            'company_id': False,
        })
        cls.child = cls.env['res.partner'].create({
            'name': 'Ahmed',
            'parent_id': cls.parent.id,
            'company_id': False,
        })
        cls.stranger = cls.env['res.partner'].create({
            'name': 'Unrelated Co',
            'is_company': True,
            'company_id': False,
        })

        cls.manager = cls.env['res.users'].create({
            'name': 'Document Manager',
            'login': 'pdc_manager',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('base.group_partner_manager').id,
            ])],
        })

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @classmethod
    def _attach(cls, name, model, res_id, mimetype=None, company=None):
        return cls.Attachment.create({
            'name': name,
            'raw': b'document-center-test',
            'res_model': model,
            'res_id': res_id,
            'mimetype': mimetype,
            'company_id': company.id if company else False,
        })

    def _fetch(self, partner, user=None, **options):
        partner = partner.with_user(user) if user else partner
        return partner.action_fetch_documents(options)

    def _names(self, result):
        return sorted(document['name'] for document in result['documents'])

    def _sale_journal(self):
        if 'account.move' not in self.env:
            return None
        return self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', self.company.id)], limit=1)

    # ------------------------------------------------------------------
    # 1. direct partner attachments
    # ------------------------------------------------------------------
    def test_direct_attachment_is_listed(self):
        self._attach('customer-id.jpg', 'res.partner', self.parent.id, 'image/jpeg')
        result = self._fetch(self.parent)

        self.assertEqual(self._names(result), ['customer-id.jpg'])
        document = result['documents'][0]
        self.assertEqual(document['source_model'], 'res.partner')
        self.assertEqual(document['file_type'], 'image')
        self.assertEqual(result['kpi']['image'], 1)
        self.assertEqual(result['total'], 1)

    def test_other_partner_documents_are_not_listed(self):
        self._attach('mine.pdf', 'res.partner', self.parent.id)
        self._attach('theirs.pdf', 'res.partner', self.stranger.id)

        self.assertEqual(self._names(self._fetch(self.parent)), ['mine.pdf'])
        self.assertEqual(self._names(self._fetch(self.stranger)), ['theirs.pdf'])

    def test_binary_field_attachments_are_excluded(self):
        """The storage behind a binary field is an ir.attachment too.

        An avatar or a cached report is stored with ``res_field`` set; those
        are field payloads, not documents, and must never reach the list.
        """
        self.Attachment.create({
            'name': 'avatar_payload',
            'raw': b'not-a-document',
            'res_model': 'res.partner',
            'res_id': self.parent.id,
            'res_field': 'image_1920',
        })
        self._attach('real-document.pdf', 'res.partner', self.parent.id)

        result = self._fetch(self.parent)
        self.assertEqual(self._names(result), ['real-document.pdf'],
                         "a res_field attachment leaked into the list")

    # ------------------------------------------------------------------
    # 2. partner hierarchy scope
    # ------------------------------------------------------------------
    def test_scope_self_versus_commercial(self):
        self._attach('parent.pdf', 'res.partner', self.parent.id)
        self._attach('child.pdf', 'res.partner', self.child.id)

        self.assertEqual(self._names(self._fetch(self.parent, scope='self')), ['parent.pdf'])
        self.assertEqual(
            self._names(self._fetch(self.parent, scope='commercial')),
            ['child.pdf', 'parent.pdf'],
        )
        # A contact opened on its own still defaults to itself only.
        self.assertEqual(self._names(self._fetch(self.child, scope='self')), ['child.pdf'])

    def test_commercial_scope_does_not_cross_entities(self):
        self._attach('parent.pdf', 'res.partner', self.parent.id)
        self._attach('stranger.pdf', 'res.partner', self.stranger.id)
        self.assertEqual(
            self._names(self._fetch(self.parent, scope='commercial')), ['parent.pdf'])

    def test_scope_available_flag(self):
        self.assertTrue(self._fetch(self.parent)['scope_available'])
        self.assertFalse(self._fetch(self.stranger)['scope_available'])

    # ------------------------------------------------------------------
    # 3. deduplication
    # ------------------------------------------------------------------
    def test_registry_keeps_one_source_per_model(self):
        sources = self.env['partner.document.source']._get_available_sources()
        models = [source['model'] for source in sources]
        self.assertEqual(len(models), len(set(models)),
                         "the registry returned two sources for the same model")

    def test_document_reachable_twice_is_listed_once(self):
        """Two sources claiming one model must not double the attachment."""
        self._attach('once.pdf', 'res.partner', self.parent.id)
        Source = self.env['partner.document.source']
        original = type(Source)._get_source_definitions

        def duplicated(source_self):
            definitions = original(source_self)
            return definitions + [{
                'code': 'partner_duplicate',
                'model': 'res.partner',
                'partner_fields': ['id'],
                'group': 'other',
                'label': 'Duplicate',
                'sequence': 500,
            }]

        with patch.object(type(Source), '_get_source_definitions', duplicated):
            result = self._fetch(self.parent)

        self.assertEqual(self._names(result), ['once.pdf'])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['kpi']['total'], 1)

    # ------------------------------------------------------------------
    # 4. accounting / purchase sources
    # ------------------------------------------------------------------
    def _create_invoice(self, partner, move_type='out_invoice', company=None):
        journal_type = 'sale' if move_type.startswith('out_') else 'purchase'
        company = company or self.company
        journal = self.env['account.journal'].search(
            [('type', '=', journal_type), ('company_id', '=', company.id)], limit=1)
        if not journal:
            self.skipTest("No %s journal configured on %s" % (journal_type, company.name))
        return self.env['account.move'].with_company(company).create({
            'move_type': move_type,
            'partner_id': partner.id,
            'journal_id': journal.id,
            'company_id': company.id,
            'invoice_line_ids': [],
        })

    def test_customer_invoice_attachment_is_listed(self):
        if 'account.move' not in self.env:
            self.skipTest("account is not installed")
        invoice = self._create_invoice(self.parent, 'out_invoice')
        self._attach('invoice.pdf', 'account.move', invoice.id, 'application/pdf')

        result = self._fetch(self.parent)
        document = next(d for d in result['documents'] if d['name'] == 'invoice.pdf')
        self.assertEqual(document['source_model'], 'account.move')
        self.assertEqual(document['source_record_id'], invoice.id)
        # The user must see "Customer Invoice", never "account.move".
        self.assertEqual(document['source_label'], 'Customer Invoice')
        self.assertTrue(document['can_open_source'])

    def test_vendor_bill_attachment_is_listed_with_its_own_label(self):
        if 'account.move' not in self.env:
            self.skipTest("account is not installed")
        bill = self._create_invoice(self.parent, 'in_invoice')
        self._attach('bill.pdf', 'account.move', bill.id, 'application/pdf')

        result = self._fetch(self.parent)
        document = next(d for d in result['documents'] if d['name'] == 'bill.pdf')
        self.assertEqual(document['source_label'], 'Vendor Bill')

    def test_purchase_order_attachment_is_listed(self):
        if 'purchase.order' not in self.env:
            self.skipTest("purchase is not installed")
        order = self.env['purchase.order'].create({'partner_id': self.parent.id})
        self._attach('po.pdf', 'purchase.order', order.id, 'application/pdf')

        result = self._fetch(self.parent)
        document = next(d for d in result['documents'] if d['name'] == 'po.pdf')
        self.assertEqual(document['source_model'], 'purchase.order')
        self.assertEqual(document['source_group'], 'purchase')

    # ------------------------------------------------------------------
    # 5. security
    # ------------------------------------------------------------------
    def test_model_acl_blocks_a_source(self):
        """A user without accounting access must not reach invoice files."""
        if 'account.move' not in self.env:
            self.skipTest("account is not installed")
        invoice = self._create_invoice(self.parent, 'out_invoice')
        self._attach('secret-invoice.pdf', 'account.move', invoice.id)
        self._attach('public-note.pdf', 'res.partner', self.parent.id)

        if self.env['account.move'].with_user(self.manager).browse().has_access('read'):
            self.skipTest("this database grants account.move read to plain users")

        result = self._fetch(self.parent, user=self.manager)
        self.assertEqual(self._names(result), ['public-note.pdf'])
        self.assertNotIn(
            'secret-invoice.pdf', self._names(result),
            "the Document Center bypassed the accounting ACL",
        )

    def test_record_rule_blocks_a_document(self):
        """Multi-company: a record the user cannot read stays invisible.

        Uses the standard res.partner company rule, so the test exercises the
        real cascade without needing a chart of accounts on the second company.
        """
        other_company = self.env['res.company'].create({'name': 'PDC Second Company'})
        contact_b = self.env['res.partner'].create({
            'name': 'Contact of Company B',
            'parent_id': self.parent.id,
            'company_id': other_company.id,
        })
        self.assertTrue(contact_b.partner_share, "the company rule would not apply")

        self._attach('other-company.pdf', 'res.partner', contact_b.id, company=other_company)
        self._attach('own-company.pdf', 'res.partner', self.parent.id)

        # self.manager is allowed in the main company only.
        names = self._names(self._fetch(self.parent, user=self.manager, scope='commercial'))
        self.assertIn('own-company.pdf', names)
        self.assertNotIn(
            'other-company.pdf', names,
            "a document of another company leaked through the Document Center",
        )
        # ... while a user allowed in both companies does see it.
        multi = self.manager.with_user(self.manager).sudo()
        multi.write({'company_ids': [(6, 0, [self.company.id, other_company.id])]})
        allowed = self.manager.with_company(other_company).with_context(
            allowed_company_ids=[self.company.id, other_company.id])
        names = self._names(
            self.parent.with_user(allowed).action_fetch_documents({'scope': 'commercial'}))
        self.assertIn('other-company.pdf', names)

    def test_record_rule_blocks_an_invoice_document(self):
        """Same cascade, through account.move's own company rule."""
        if 'account.move' not in self.env:
            self.skipTest("account is not installed")
        other_company = self.env['res.company'].create({'name': 'PDC Invoice Company'})
        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', other_company.id)], limit=1)
        if not journal:
            self.skipTest("no chart of accounts on the second company")

        invoice = self._create_invoice(self.parent, 'out_invoice', company=other_company)
        self._attach('other-company.pdf', 'account.move', invoice.id, company=other_company)
        self._attach('own-company.pdf', 'res.partner', self.parent.id)

        accountant = self.env['res.users'].create({
            'name': 'Accountant Company A',
            'login': 'pdc_accountant_a',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_manager').id,
            ])],
        })

        names = self._names(self._fetch(self.parent, user=accountant))
        self.assertIn('own-company.pdf', names)
        self.assertNotIn('other-company.pdf', names)

    def test_open_source_rejects_unrelated_models(self):
        """The open-source endpoint is not a generic record opener."""
        attachment = self._attach('note.pdf', 'ir.ui.view',
                                  self.env.ref('base.view_partner_form').id)
        with self.assertRaises(Exception):
            self.Center.action_open_source(attachment.id)

    def test_open_source_returns_the_record(self):
        attachment = self._attach('note.pdf', 'res.partner', self.stranger.id)
        action = self.Center.action_open_source(attachment.id)
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['res_id'], self.stranger.id)

    def test_delete_is_refused_on_business_documents(self):
        if 'purchase.order' not in self.env:
            self.skipTest("purchase is not installed")
        order = self.env['purchase.order'].create({'partner_id': self.parent.id})
        attachment = self._attach('po.pdf', 'purchase.order', order.id)
        with self.assertRaises(Exception):
            self.Center.action_delete(attachment.id)
        self.assertTrue(attachment.exists())

    def test_delete_is_allowed_on_contact_files(self):
        attachment = self._attach('note.pdf', 'res.partner', self.parent.id)
        self.Center.action_delete(attachment.id)
        self.assertFalse(attachment.exists())

    # ------------------------------------------------------------------
    # 6. search, filters, pagination
    # ------------------------------------------------------------------
    def test_search_by_filename(self):
        self._attach('contract-2026.pdf', 'res.partner', self.parent.id)
        self._attach('photo.jpg', 'res.partner', self.parent.id, 'image/jpeg')

        self.assertEqual(self._names(self._fetch(self.parent, search='contract')),
                         ['contract-2026.pdf'])
        self.assertEqual(self._names(self._fetch(self.parent, search='CONTRACT')),
                         ['contract-2026.pdf'])
        self.assertEqual(self._fetch(self.parent, search='nothing-matches')['total'], 0)

    def test_search_by_source_reference(self):
        if 'purchase.order' not in self.env:
            self.skipTest("purchase is not installed")
        order = self.env['purchase.order'].create({'partner_id': self.parent.id})
        self._attach('scan001.pdf', 'purchase.order', order.id)
        self._attach('unrelated.pdf', 'res.partner', self.parent.id)

        # Scoped to files: the order's own live document answers this search
        # too, and that is covered in test_live_documents.
        result = self._fetch(self.parent, search=order.name, doc_kind='attachment')
        self.assertEqual(self._names(result), ['scan001.pdf'],
                         "searching the source document reference did not work")

    def test_search_by_reference_also_finds_the_live_document(self):
        if 'purchase.order' not in self.env:
            self.skipTest("purchase is not installed")
        order = self.env['purchase.order'].create({'partner_id': self.parent.id})
        self._attach('scan001.pdf', 'purchase.order', order.id)
        self._attach('unrelated.pdf', 'res.partner', self.parent.id)

        result = self._fetch(self.parent, search=order.name)
        kinds = {document['kind'] for document in result['documents']}
        self.assertEqual(kinds, {'record', 'attachment'})
        self.assertNotIn('unrelated.pdf', self._names(result))

    def test_file_type_filter_and_kpis(self):
        self._attach('a.pdf', 'res.partner', self.parent.id, 'application/pdf')
        self._attach('b.png', 'res.partner', self.parent.id, 'image/png')
        self._attach('c.docx', 'res.partner', self.parent.id,
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document')

        everything = self._fetch(self.parent)
        self.assertEqual(everything['kpi']['pdf'], 1)
        self.assertEqual(everything['kpi']['image'], 1)
        self.assertEqual(everything['kpi']['document'], 1)

        pdf_only = self._fetch(self.parent, file_type='pdf')
        self.assertEqual(self._names(pdf_only), ['a.pdf'])
        # KPIs keep describing the whole set while a type facet is active.
        self.assertEqual(pdf_only['kpi']['total'], 3)

    def test_file_type_falls_back_to_extension(self):
        self._attach('report.pdf', 'res.partner', self.parent.id,
                     'application/octet-stream')
        result = self._fetch(self.parent)
        self.assertEqual(result['documents'][0]['file_type'], 'pdf')

    def test_pagination(self):
        for index in range(7):
            self._attach('file-%02d.pdf' % index, 'res.partner', self.parent.id)

        first = self._fetch(self.parent, limit=3, offset=0, order='name_asc')
        self.assertEqual(first['total'], 7)
        self.assertEqual(len(first['documents']), 3)
        self.assertEqual(self._names(first), ['file-00.pdf', 'file-01.pdf', 'file-02.pdf'])

        last = self._fetch(self.parent, limit=3, offset=6, order='name_asc')
        self.assertEqual(last['total'], 7)
        self.assertEqual(self._names(last), ['file-06.pdf'])

    def test_ordering(self):
        small = self._attach('small.pdf', 'res.partner', self.parent.id)
        big = self.Attachment.create({
            'name': 'big.pdf',
            'raw': b'x' * 5000,
            'res_model': 'res.partner',
            'res_id': self.parent.id,
        })
        by_size = self._fetch(self.parent, order='size_desc')
        self.assertEqual(
            [d['attachment_id'] for d in by_size['documents']], [big.id, small.id])

    def test_invalid_options_fall_back_to_defaults(self):
        self._attach('a.pdf', 'res.partner', self.parent.id)
        result = self._fetch(
            self.parent, scope='everything', order='; DROP TABLE',
            file_type='exe', limit=99999, offset=-4,
        )
        self.assertEqual(result['scope'], 'self')
        self.assertEqual(result['limit'], self.Center._MAX_LIMIT)
        self.assertEqual(result['offset'], 0)
        self.assertEqual(result['total'], 1)

    # ------------------------------------------------------------------
    # 7. metadata
    # ------------------------------------------------------------------
    def test_important_flag_and_filter(self):
        important = self._attach('important.pdf', 'res.partner', self.parent.id)
        self._attach('ordinary.pdf', 'res.partner', self.parent.id)

        self.Center.action_set_metadata(important.id, {'is_important': True})
        self.assertEqual(self._names(self._fetch(self.parent, important_only=True)),
                         ['important.pdf'])
        self.assertEqual(self._fetch(self.parent)['total'], 2)

    def test_category_filter(self):
        category = self.env.ref('partner_document_center.category_contract')
        categorised = self._attach('contract.pdf', 'res.partner', self.parent.id)
        self._attach('other.pdf', 'res.partner', self.parent.id)

        self.Center.action_set_metadata(categorised.id, {'category_id': category.id})
        result = self._fetch(self.parent, category_id=category.id)
        self.assertEqual(self._names(result), ['contract.pdf'])
        self.assertEqual(result['documents'][0]['category_name'], category.name)

    def test_metadata_does_not_duplicate_the_attachment(self):
        attachment = self._attach('one.pdf', 'res.partner', self.parent.id)
        self.Center.action_set_metadata(attachment.id, {'is_important': True})
        self.assertEqual(
            self.Attachment.search_count([('name', '=', 'one.pdf')]), 1,
            "metadata created a second copy of the attachment",
        )

    def test_rename(self):
        attachment = self._attach('old.pdf', 'res.partner', self.parent.id)
        self.Center.action_rename(attachment.id, 'new.pdf')
        self.assertEqual(attachment.name, 'new.pdf')

    # ------------------------------------------------------------------
    # 8. counting (smart button)
    # ------------------------------------------------------------------
    def test_count_matches_the_listed_total(self):
        self._attach('a.pdf', 'res.partner', self.parent.id)
        self._attach('b.pdf', 'res.partner', self.child.id)
        if 'purchase.order' in self.env:
            order = self.env['purchase.order'].create({'partner_id': self.parent.id})
            self._attach('po.pdf', 'purchase.order', order.id)

        for scope in ('self', 'commercial'):
            self.assertEqual(
                self.parent.action_count_documents(scope),
                self._fetch(self.parent, scope=scope)['total'],
                "smart button count disagrees with the list for scope %r" % scope,
            )

    def test_metadata_cannot_be_written_without_attachment_write_access(self):
        """The metadata model is RPC-reachable; it must gate on the document."""
        if 'purchase.order' not in self.env:
            self.skipTest("purchase is not installed")
        order = self.env['purchase.order'].create({'partner_id': self.parent.id})
        attachment = self._attach('po.pdf', 'purchase.order', order.id)

        Metadata = self.env['partner.document.metadata'].with_user(self.manager)
        if attachment.with_user(self.manager).has_access('write'):
            self.skipTest("this user can write the attachment anyway")
        with self.assertRaises(Exception):
            Metadata.create({'attachment_id': attachment.id, 'is_important': True})

    def test_metadata_write_is_allowed_on_own_contact_files(self):
        attachment = self._attach('note.pdf', 'res.partner', self.parent.id)
        metadata = self.env['partner.document.metadata'].create({
            'attachment_id': attachment.id, 'is_important': True,
        })
        self.assertTrue(metadata.is_important)
        metadata.write({'is_important': False})
        self.assertFalse(metadata.is_important)
