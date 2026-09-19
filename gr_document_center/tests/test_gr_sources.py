# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGrDocumentSources(TransactionCase):
    """The bridge adds sources without touching the Document Center itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Bridge Test Customer',
            'is_company': True,
        })

    def _sources(self):
        return {
            source['code']: source
            for source in self.env['partner.document.source']._get_available_sources()
        }

    def test_gr_sources_are_registered(self):
        sources = self._sources()
        self.assertIn('gr_rental_order', sources)
        self.assertEqual(sources['gr_rental_order']['model'], 'gr.rental.order')
        self.assertEqual(sources['gr_rental_order']['group'], 'rental')
        self.assertEqual(sources['gr_rental_order']['partner_fields'], ['partner_id'])

    def test_indirect_partner_paths_survive_validation(self):
        """The dotted routes are accepted, not silently dropped."""
        sources = self._sources()
        if 'gr_maintenance_job' in sources:
            self.assertEqual(
                sources['gr_maintenance_job']['partner_fields'],
                ['asset_id.owner_partner_id'],
            )
        if 'gr_contract_amendment' in sources:
            self.assertEqual(
                sources['gr_contract_amendment']['partner_fields'],
                ['contract_id.partner_id'],
            )

    def test_vendor_sources_use_the_vendor_field(self):
        sources = self._sources()
        for code in ('gr_sublet_agreement', 'gr_parts_request'):
            if code in sources:
                self.assertEqual(sources[code]['partner_fields'], ['vendor_id'])
                self.assertEqual(sources[code]['group'], 'purchase')

    def test_customer_approval_documents_are_registered_when_available(self):
        if 'gr.customer.approval.document' not in self.env:
            self.skipTest("gr_customer_approval is not installed")
        sources = self._sources()
        self.assertIn('gr_customer_approval_document', sources)
        source = sources['gr_customer_approval_document']
        self.assertEqual(source['model'], 'gr.customer.approval.document')
        self.assertEqual(source['partner_fields'], ['partner_id'])
        self.assertEqual(source['group'], 'rental')
        self.assertEqual(source['date_field'], 'generated_at')
        self.assertEqual(source['state_field'], 'state')

    def test_customer_approval_document_reaches_the_document_center(self):
        if 'gr.customer.approval.document' not in self.env:
            self.skipTest("gr_customer_approval is not installed")
        document = self.env['gr.customer.approval.document'].with_context(
            approval_document_internal=True).create({
                'name': 'approval-version-1.pdf',
                'report_type': 'delivery',
                'document_model': 'gr.rental.order',
                'document_res_id': 1,
                'document_number': 'RO-TEST',
                'document_ref': 'Delivery Note',
                'partner_id': self.partner.id,
                'company_id': self.env.company.id,
                'language': 'en_US',
                'version': 1,
                'state': 'pending',
                'content_hash': 'approval-hash',
                'generated_at': '2026-08-16 00:00:00',
            })

        result = self.partner.action_fetch_documents({
            'source': 'src:gr_customer_approval_document',
        })
        matching = [
            item for item in result['documents']
            if item['source_model'] == 'gr.customer.approval.document'
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['kind'], 'record')
        self.assertEqual(matching[0]['name'], document.display_name)
        self.assertEqual(matching[0]['source_label'], 'Delivery Report')
        self.assertEqual(matching[0]['source_record_id'], document.id)
        self.assertTrue(matching[0]['can_open_source'])

    def test_rental_order_attachment_reaches_the_document_center(self):
        if 'gr.rental.order' not in self.env:
            self.skipTest("gr_rental_order is not installed")
        order = self.env['gr.rental.order'].create({
            'partner_id': self.partner.id,
            'company_id': self.env.company.id,
        })
        self.env['ir.attachment'].create({
            'name': 'rental-contract.pdf',
            'raw': b'bridge-test',
            'res_model': 'gr.rental.order',
            'res_id': order.id,
        })

        result = self.partner.action_fetch_documents({})
        names = [document['name'] for document in result['documents']]
        self.assertIn('rental-contract.pdf', names)

        document = next(d for d in result['documents'] if d['name'] == 'rental-contract.pdf')
        self.assertEqual(document['source_label'], 'Rental Order')
        self.assertEqual(document['source_display_name'], order.name)
        self.assertEqual(document['source_group'], 'rental')
        # A rental order's attachment is part of that order, not a loose
        # contact file: the Document Center must not offer to delete it.
        self.assertFalse(document['can_delete'])
        self.assertTrue(document['can_open_source'])

        self.assertEqual(self.partner.action_count_documents('self'), result['total'])
