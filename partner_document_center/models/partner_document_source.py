# -*- coding: utf-8 -*-
"""Declarative registry of the models the Document Center aggregates from.

A *source* answers one question: "given a partner, which records of model X
belong to it?".  It answers it with real relational fields only - never with a
name or e-mail match - and it is resolved against the running registry, so a
module that is not installed simply yields no source instead of an import
error.

Extending it from another module is a single method override::

    class PartnerDocumentSource(models.AbstractModel):
        _inherit = 'partner.document.source'

        @api.model
        def _get_source_definitions(self):
            return super()._get_source_definitions() + [{
                'code': 'gr_rental_order',
                'model': 'gr.rental.order',
                'partner_fields': ['partner_id'],
                'group': 'rental',
                'label': self.env._('Rental Order'),
                'sequence': 110,
            }]
"""
import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class PartnerDocumentSource(models.AbstractModel):
    _name = 'partner.document.source'
    _description = 'Partner Document Source Registry'

    # UI buckets the filter chips are built from. Order matters: it is the
    # order the chips appear in.
    GROUP_SEQUENCE = (
        'partner', 'sales', 'accounting', 'purchase', 'inventory',
        'crm', 'project', 'rental', 'maintenance', 'other',
    )

    @api.model
    def _get_group_labels(self):
        return {
            'partner': _('Contact'),
            'sales': _('Sales'),
            'accounting': _('Invoicing'),
            'purchase': _('Purchase'),
            'inventory': _('Inventory'),
            'crm': _('CRM'),
            'project': _('Projects'),
            'rental': _('Rental'),
            'maintenance': _('Maintenance'),
            'other': _('Other'),
        }

    @api.model
    def _get_source_definitions(self):
        """Return the raw source definitions, before availability filtering.

        Each definition is a dict:

        ``code``            unique key, used by the client-side filters
        ``model``           the ``res_model`` its attachments carry. One source
                            per model: subtypes are expressed with
                            ``subtype_field`` rather than with a second source,
                            so that per-source counts stay additive.
        ``partner_fields``  stored many2one fields to ``res.partner`` (the
                            literal ``'id'`` is accepted for ``res.partner``
                            itself). Several fields are OR-ed together.
        ``group``           UI bucket, see :attr:`GROUP_SEQUENCE`
        ``label``           human label, used when no subtype matches
        ``sequence``        ordering, and tie-break when two sources would
                            claim the same attachment
        ``domain``          optional extra restriction on the source records
        ``subtype_field``   optional selection field refining the label
        ``subtype_labels``  optional {selection value: label}

        A source may also publish its records as *live documents* - cards that
        stand for the business record itself, with no attachment behind them:

        ``document_record`` publish the records as live documents (default
                            True; ``res.partner`` opts out, a contact is not a
                            document of itself)
        ``report_xmlid``    ir.actions.report to print/preview the record. The
                            report is rendered on demand from the current
                            record, never stored.
        ``date_field``      the document's own date, falling back to
                            ``create_date``
        ``state_field``     selection field shown as the status badge
        ``amount_field``    monetary total
        ``currency_field``  currency of ``amount_field``

        None of these copy anything: they name fields that are read live off
        the record whenever a page is rendered.

        Overrides must call ``super()`` and append.
        """
        return [
            {
                'code': 'partner',
                'model': 'res.partner',
                'partner_fields': ['id'],
                'group': 'partner',
                'label': _('Contact'),
                'sequence': 10,
                # A contact is not one of its own documents.
                'document_record': False,
            },
            {
                'code': 'sale_order',
                'model': 'sale.order',
                'partner_fields': ['partner_id'],
                'group': 'sales',
                'label': _('Sales Order'),
                'sequence': 20,
                'subtype_field': 'state',
                'subtype_labels': {
                    'draft': _('Quotation'),
                    'sent': _('Quotation'),
                },
                'report_xmlid': 'sale.action_report_saleorder',
                'date_field': 'date_order',
                'state_field': 'state',
                'amount_field': 'amount_total',
                'currency_field': 'currency_id',
            },
            {
                'code': 'account_move',
                'model': 'account.move',
                'partner_fields': ['partner_id'],
                'group': 'accounting',
                'label': _('Journal Entry'),
                'sequence': 30,
                'subtype_field': 'move_type',
                'subtype_labels': {
                    'out_invoice': _('Customer Invoice'),
                    'out_refund': _('Customer Credit Note'),
                    'in_invoice': _('Vendor Bill'),
                    'in_refund': _('Vendor Credit Note'),
                    'out_receipt': _('Sales Receipt'),
                    'in_receipt': _('Purchase Receipt'),
                    'entry': _('Journal Entry'),
                },
                'report_xmlid': 'account.account_invoices',
                'date_field': 'invoice_date',
                'state_field': 'state',
                'amount_field': 'amount_total',
                'currency_field': 'currency_id',
            },
            {
                'code': 'account_payment',
                'model': 'account.payment',
                'partner_fields': ['partner_id'],
                'group': 'accounting',
                'label': _('Payment'),
                'sequence': 40,
                'report_xmlid': 'account.action_report_payment_receipt',
                'date_field': 'date',
                'state_field': 'state',
                'amount_field': 'amount',
                'currency_field': 'currency_id',
            },
            {
                'code': 'purchase_order',
                'model': 'purchase.order',
                'partner_fields': ['partner_id'],
                'group': 'purchase',
                'label': _('Purchase Order'),
                'sequence': 50,
                'subtype_field': 'state',
                'subtype_labels': {
                    'draft': _('Request for Quotation'),
                    'sent': _('Request for Quotation'),
                },
                'report_xmlid': 'purchase.action_report_purchase_order',
                'date_field': 'date_order',
                'state_field': 'state',
                'amount_field': 'amount_total',
                'currency_field': 'currency_id',
            },
            {
                'code': 'stock_picking',
                'model': 'stock.picking',
                'partner_fields': ['partner_id'],
                'group': 'inventory',
                'label': _('Stock Transfer'),
                'sequence': 60,
                'subtype_field': 'picking_type_code',
                'subtype_labels': {
                    'outgoing': _('Delivery Order'),
                    'incoming': _('Receipt'),
                    'internal': _('Internal Transfer'),
                },
                'report_xmlid': 'stock.action_report_delivery',
                'date_field': 'scheduled_date',
                'state_field': 'state',
            },
            {
                'code': 'crm_lead',
                'model': 'crm.lead',
                'partner_fields': ['partner_id'],
                'group': 'crm',
                'label': _('Lead / Opportunity'),
                'sequence': 70,
                'subtype_field': 'type',
                'subtype_labels': {
                    'lead': _('Lead'),
                    'opportunity': _('Opportunity'),
                },
                'date_field': 'date_deadline',
                'state_field': 'stage_id',
                'amount_field': 'expected_revenue',
                'currency_field': 'company_currency',
            },
            {
                'code': 'project_project',
                'model': 'project.project',
                'partner_fields': ['partner_id'],
                'group': 'project',
                'label': _('Project'),
                'sequence': 80,
                'date_field': 'date_start',
            },
            {
                'code': 'project_task',
                'model': 'project.task',
                'partner_fields': ['partner_id'],
                'group': 'project',
                'label': _('Task'),
                'sequence': 90,
                'date_field': 'date_deadline',
                'state_field': 'state',
            },
            {
                'code': 'helpdesk_ticket',
                'model': 'helpdesk.ticket',
                'partner_fields': ['partner_id'],
                'group': 'other',
                'label': _('Helpdesk Ticket'),
                'sequence': 100,
                'state_field': 'stage_id',
            },
        ]

    @api.model
    def _get_available_sources(self):
        """Normalised, de-duplicated, access-filtered source list.

        A definition survives only if its model is in the registry, is a real
        stored model, the user has model-level read permission on it, and at
        least one declared partner field genuinely exists as a stored many2one
        to ``res.partner``.  That last check is what keeps a typo in a bridge
        module from silently widening or breaking the aggregation.
        """
        sources = {}
        for definition in self._get_source_definitions():
            source = self._normalise_source(definition)
            if not source:
                continue
            model = source['model']
            previous = sources.get(model)
            if previous is not None:
                # One source per model, otherwise per-source counts would
                # double-count and the totals shown on the smart button would
                # drift from the list. Lowest sequence wins.
                _logger.warning(
                    "Partner Document Center: sources %r and %r both declare "
                    "model %r; keeping %r.",
                    previous['code'], source['code'], model,
                    min(previous, source, key=lambda s: (s['sequence'], s['code']))['code'],
                )
                if (previous['sequence'], previous['code']) <= (source['sequence'], source['code']):
                    continue
            sources[model] = source

        group_order = {group: index for index, group in enumerate(self.GROUP_SEQUENCE)}
        return sorted(
            sources.values(),
            key=lambda s: (group_order.get(s['group'], len(group_order)), s['sequence'], s['code']),
        )

    @api.model
    def _normalise_source(self, definition):
        """Validate one definition against the live registry, or return None."""
        model_name = definition.get('model')
        code = definition.get('code')
        if not model_name or not code:
            _logger.warning("Partner Document Center: ignoring source without code/model: %r", definition)
            return None

        # Runtime availability: this is what makes sale/crm/project/... optional.
        Model = self.env.get(model_name)
        if Model is None or Model._abstract or Model._transient:
            return None
        # Model-level ACL. Cheap, and it spares us a query per source for
        # models the user may not read at all.
        if not Model.browse().has_access('read'):
            return None

        partner_fields = []
        for field_name in definition.get('partner_fields') or []:
            if field_name == 'id' and model_name == 'res.partner':
                partner_fields.append('id')
                continue
            if self._is_partner_path(Model, field_name):
                partner_fields.append(field_name)
            else:
                _logger.warning(
                    "Partner Document Center: source %r declares %r.%r which is "
                    "not a stored relation to res.partner; skipping that field.",
                    code, model_name, field_name,
                )
        if not partner_fields:
            return None

        subtype_field = definition.get('subtype_field')
        if subtype_field and subtype_field not in Model._fields:
            subtype_field = None

        group = definition.get('group') or 'other'
        return {
            'code': code,
            'model': model_name,
            'partner_fields': partner_fields,
            'group': group,
            'label': definition.get('label') or Model._description or model_name,
            'sequence': definition.get('sequence', 100),
            'domain': definition.get('domain') or [],
            'subtype_field': subtype_field,
            'subtype_labels': definition.get('subtype_labels') or {},
            # --- live document contract -------------------------------
            # Publishing records is the default: a source registered by a
            # future module becomes a live document without saying so. A
            # provider that only carries files opts out explicitly.
            'document_record': definition.get('document_record', True),
            'report_xmlid': definition.get('report_xmlid') or False,
            'date_field': self._valid_field(
                Model, definition.get('date_field'), ('date', 'datetime')),
            'state_field': self._valid_field(
                Model, definition.get('state_field'), ('selection', 'many2one', 'char')),
            'amount_field': self._valid_field(
                Model, definition.get('amount_field'), ('float', 'monetary')),
            'currency_field': self._valid_field(
                Model, definition.get('currency_field'), ('many2one',)),
            'rec_name_field': self._valid_field(
                Model, Model._rec_name, ('char', 'text')),
        }

    @api.model
    def _valid_field(self, Model, field_name, types):
        """Return ``field_name`` if it exists on ``Model`` with a usable type.

        Summary fields are advisory: a provider naming a field that a given
        Odoo edition or module version does not have loses that one line of
        the card, it does not break the source.
        """
        if not field_name:
            return False
        field = Model._fields.get(field_name)
        if field is None or not field.store or field.type not in types:
            return False
        return field_name

    @api.model
    def _get_source_report(self, source):
        """The report action of a source, or an empty recordset.

        Resolved on demand rather than stored on the source: the xmlid lookup
        is ormcached, and a report belonging to an uninstalled module simply
        yields nothing instead of raising.
        """
        xmlid = source.get('report_xmlid')
        if not xmlid:
            return self.env['ir.actions.report'].browse()
        report = self.env.ref(xmlid, raise_if_not_found=False)
        if not report or report._name != 'ir.actions.report':
            return self.env['ir.actions.report'].browse()
        return report

    @api.model
    def _prepare_live_document_values(self, source, record, values):
        """Hook: enrich one live document card.

        ``values`` is the normalised dict about to be sent to the client, and
        the declared summary fields are already prefetched on ``record``, so an
        override can add its own without costing a query per card::

            def _prepare_live_document_values(self, source, record, values):
                values = super()._prepare_live_document_values(source, record, values)
                if source['code'] == 'gr_rental_order':
                    values['subtitle'] = record.asset_id.display_name
                return values
        """
        return values

    @api.model
    def _is_partner_path(self, Model, path):
        """Is ``path`` a stored relational route from ``Model`` to res.partner?

        Accepts a plain field (``partner_id``) and a dotted route through
        many2one hops (``asset_id.owner_partner_id``), which is what lets a
        record that has no partner of its own - a maintenance job on a
        customer-owned generator - still belong to that customer. Every hop
        must be a *stored* many2one, so the whole thing stays one indexed SQL
        join and never degrades into a Python walk.
        """
        current = Model
        parts = path.split('.')
        for index, part in enumerate(parts):
            field = current._fields.get(part)
            if field is None or not field.store:
                return False
            is_last = index == len(parts) - 1
            if is_last:
                return field.type == 'many2one' and field.comodel_name == 'res.partner'
            if field.type != 'many2one':
                return False
            current = self.env.get(field.comodel_name)
            if current is None:
                return False
        return False

    @api.model
    def _get_source_record_domain(self, source, partner_ids):
        """Domain selecting the records of ``source`` that belong to ``partner_ids``."""
        conditions = []
        for field_name in source['partner_fields']:
            conditions.append([(field_name, 'in', partner_ids)])
        domain = conditions[0]
        for extra in conditions[1:]:
            domain = ['|'] + domain + extra
        return list(source['domain']) + domain
