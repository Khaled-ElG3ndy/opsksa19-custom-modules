# -*- coding: utf-8 -*-
"""Registers the gr_* business records as partner document sources.

This is the whole module. Adding a source is one dict; the Document Center
needs no change, and a gr_* module that is not installed simply drops out at
registry-resolution time.
"""
from odoo import _, api, models


class PartnerDocumentSource(models.AbstractModel):
    _inherit = 'partner.document.source'

    @api.model
    def _get_source_definitions(self):
        return super()._get_source_definitions() + [
            # -------------------------------------------------- rental
            {
                'code': 'gr_rental_order',
                'model': 'gr.rental.order',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': _('Rental Order'),
                'sequence': 200,
                'report_xmlid': 'gr_rental_order.action_report_gr_delivery_note',
                'date_field': 'date_requested',
                'state_field': 'state',
            },
            {
                'code': 'gr_rental_contract',
                'model': 'gr.rental.contract',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': _('Rental Contract'),
                'sequence': 210,
                'report_xmlid': 'gr_contract.action_report_gr_rental_contract',
                'date_field': 'date_start',
                'state_field': 'state',
                'currency_field': 'currency_id',
            },
            {
                # No partner of its own: an amendment belongs to whoever the
                # amended contract belongs to.
                'code': 'gr_contract_amendment',
                'model': 'gr.contract.amendment',
                'partner_fields': ['contract_id.partner_id'],
                'group': 'rental',
                'label': _('Contract Amendment'),
                'sequence': 220,
                'date_field': 'request_date',
                'state_field': 'state',
                'currency_field': 'currency_id',
            },
            {
                'code': 'gr_customer_site',
                'model': 'gr.customer.site',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': _('Customer Site'),
                'sequence': 230,
            },
            {
                'code': 'gr_rental_inspection',
                'model': 'gr.rental.inspection',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': _('Rental Inspection'),
                'sequence': 240,
                'report_xmlid': 'gr_customer_approval.action_report_approval_delivery',
                'state_field': 'state',
            },
            {
                'code': 'gr_hour_log',
                'model': 'gr.hour.log',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': _('Hour Log'),
                'sequence': 250,
                'state_field': 'state',
            },
            {
                'code': 'gr_customer_approval_document',
                'model': 'gr.customer.approval.document',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': _('Customer Approval Document'),
                'sequence': 260,
                'subtype_field': 'report_type',
                'subtype_labels': {
                    'rental_order': _('Rental Agreement'),
                    'delivery': _('Delivery Report'),
                    'visit': _('Visit Report'),
                    'return': _('Return Report'),
                },
                'date_field': 'generated_at',
                'state_field': 'state',
            },

            # -------------------------------------------------- maintenance
            {
                'code': 'gr_maintenance_contract',
                'model': 'gr.maintenance.contract',
                'partner_fields': ['partner_id'],
                'group': 'maintenance',
                'label': _('Maintenance Contract'),
                'sequence': 300,
                'date_field': 'date_start',
                'state_field': 'state',
            },
            {
                # Jobs carry no partner; a job on a customer-owned generator
                # belongs to that generator's owner.
                'code': 'gr_maintenance_job',
                'model': 'gr.maintenance.job',
                'partner_fields': ['asset_id.owner_partner_id'],
                'group': 'maintenance',
                'label': _('Maintenance Job'),
                'sequence': 310,
                'date_field': 'scheduled_date',
                'state_field': 'state',
                'currency_field': 'currency_id',
            },
            {
                'code': 'gr_field_worksheet',
                'model': 'gr.field.worksheet',
                'partner_fields': ['partner_id'],
                'group': 'maintenance',
                'label': _('Field Worksheet'),
                'sequence': 320,
                'report_xmlid': 'gr_customer_approval.action_report_approval_visit',
                'state_field': 'state',
            },
            {
                # Ownership only. `current_customer_id` is where the unit
                # happens to be today, which is not a document relationship:
                # it would move a generator's whole file history to whoever
                # rents it next.
                'code': 'gr_generator_asset',
                'model': 'gr.generator.asset',
                'partner_fields': ['owner_partner_id'],
                'group': 'maintenance',
                'label': _('Generator'),
                'sequence': 330,
                'currency_field': 'currency_id',
            },

            # -------------------------------------------------- money
            {
                'code': 'gr_billing_run',
                'model': 'gr.billing.run',
                'partner_fields': ['partner_id'],
                'group': 'accounting',
                'label': _('Billing Run'),
                'sequence': 400,
                'state_field': 'state',
                'currency_field': 'currency_id',
            },
            {
                'code': 'gr_sublet_agreement',
                'model': 'gr.sublet.agreement',
                'partner_fields': ['vendor_id'],
                'group': 'purchase',
                'label': _('Sublet Agreement'),
                'sequence': 410,
                'date_field': 'date_start',
                'state_field': 'state',
            },
            {
                'code': 'gr_parts_request',
                'model': 'gr.parts.request',
                'partner_fields': ['vendor_id'],
                'group': 'purchase',
                'label': _('Parts Request'),
                'sequence': 420,
                'state_field': 'state',
            },
        ]
