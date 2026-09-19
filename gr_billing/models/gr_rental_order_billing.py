# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GrRentalOrder(models.Model):
    _inherit = 'gr.rental.order'

    _INVOICEABLE_STATES = (
        'confirmed', 'reserved', 'dispatched', 'installed', 'on_rent',
        'off_hire_requested', 'returned', 'inspection', 'closed')
    _INVOICE_MOVE_TYPES = ('out_invoice', 'out_refund')

    invoice_ids = fields.Many2many(
        'account.move', string='Invoices', compute='_compute_invoice_ids')
    invoice_count = fields.Integer(
        string='Invoice Count', compute='_compute_invoice_ids')
    billable_log_count = fields.Integer(
        string='Billable Logs', compute='_compute_billable_log_count')

    def _get_invoice_candidates(self):
        orders = self.filtered('id')
        Move = self.env['account.move']
        if not orders:
            return Move

        direct_moves = Move.search([
            ('move_type', 'in', self._INVOICE_MOVE_TYPES),
            ('rental_order_id', 'in', orders.ids),
        ])

        names = [name for name in orders.mapped('name') if name]
        legacy_moves = Move
        if names:
            legacy_moves = Move.search([
                ('move_type', 'in', self._INVOICE_MOVE_TYPES),
                ('rental_order_id', '=', False),
                ('invoice_origin', 'in', names),
                ('company_id', 'in', orders.company_id.ids),
            ])
        return direct_moves | legacy_moves

    @api.depends('name')
    def _compute_invoice_ids(self):
        moves = self._get_invoice_candidates()
        empty_moves = self.env['account.move']
        for order in self:
            if not order.id:
                order.invoice_ids = empty_moves
                order.invoice_count = 0
                continue

            invoices = moves.filtered(
                lambda move: move.rental_order_id == order
                or (
                    not move.rental_order_id
                    and move.invoice_origin == order.name
                    and move.company_id == order.company_id
                )
            )
            order.invoice_ids = invoices
            order.invoice_count = len(invoices)

    def _billable_hour_logs(self):
        self.ensure_one()
        if not self.id:
            return self.env['gr.hour.log']
        return self.env['gr.hour.log'].search([
            ('rental_order_id', '=', self.id),
            ('state', '=', 'approved'),
            ('billed', '=', False),
            ('company_id', '=', self.company_id.id),
        ], order='reading_date, id')

    def _compute_billable_log_count(self):
        for order in self:
            order.billable_log_count = len(order._billable_hour_logs())

    def _get_rental_invoice_tax(self):
        self.ensure_one()
        return self.env['account.tax'].with_company(self.company_id).search([
            ('company_id', '=', self.company_id.id),
            ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 15.0),
        ], limit=1)

    def _rental_invoice_source_lines(self):
        self.ensure_one()
        if 'item_line_ids' not in self._fields:
            return self.env['gr.rental.order.line']
        return self.item_line_ids.filtered(
            lambda line: line.equipment_asset_id or line.item_unit_id)

    def _rental_invoice_serial_summary(self):
        self.ensure_one()
        names = []
        for line in self._rental_invoice_source_lines():
            name = (
                line.equipment_asset_id.display_name
                or line.item_unit_id.display_name
                or line.asset_display_name)
            if name:
                names.append(name)
        return ', '.join(dict.fromkeys(names))

    def _rental_invoice_primary_equipment_source(self):
        self.ensure_one()
        if self.asset_id:
            return self.asset_id, self.env['gr.rental.item.unit']
        line = self._rental_invoice_source_lines()[:1]
        if line:
            return line.equipment_asset_id, line.item_unit_id
        return self.env['gr.generator.asset'], self.env['gr.rental.item.unit']

    def _rental_invoice_equipment_reference(self, asset=False, unit=False):
        self.ensure_one()
        values = []
        if asset:
            values.extend([asset.code, asset.serial_number])
            if 'supplier_equipment_ref' in asset._fields:
                values.append(asset.supplier_equipment_ref)
        elif unit:
            values.extend([unit.name, unit.serial_number])
        return ' / '.join(dict.fromkeys(
            str(value) for value in values if value))

    def _rental_invoice_equipment_details(self, asset=False, unit=False):
        self.ensure_one()
        details = []
        if asset:
            if asset.code:
                details.append(_("Equipment No.: %s") % asset.code)
            if asset.serial_number:
                details.append(_("Serial Number: %s") % asset.serial_number)
            if ('supplier_equipment_ref' in asset._fields
                    and asset.supplier_equipment_ref):
                details.append(
                    _("Supplier Reference: %s") % asset.supplier_equipment_ref)
        elif unit:
            if unit.name:
                details.append(_("Equipment No.: %s") % unit.name)
            if unit.serial_number:
                details.append(_("Serial Number: %s") % unit.serial_number)
        return details

    def _rental_invoice_usage_line_name(self, label):
        self.ensure_one()
        asset, unit = self._rental_invoice_primary_equipment_source()
        asset_name = (
            (asset.display_name if asset else False)
            or (unit.display_name if unit else False))
        title = label
        if asset_name:
            title = "%s - %s" % (label, asset_name)
        details = self._rental_invoice_equipment_details(asset=asset, unit=unit)
        return '\n'.join([title] + details)

    def _rental_invoice_usage_equipment_reference(self):
        self.ensure_one()
        asset, unit = self._rental_invoice_primary_equipment_source()
        return self._rental_invoice_equipment_reference(asset=asset, unit=unit)

    def _rental_invoice_info_note(self):
        self.ensure_one()

        def add(parts, label, value):
            if value:
                parts.append(_("%(label)s: %(value)s",
                               label=label, value=value))

        parts = []
        add(parts, _("Rental Order"), self.name)
        add(parts, _("Customer"), self.partner_id.display_name)
        add(parts, _("Site"), self.site_id.display_name if self.site_id else False)
        add(parts, _("Contract"), self.contract_id.display_name if self.contract_id else False)
        add(parts, _("Customer PO"),
            self.contract_id.customer_po_number if self.contract_id else False)
        add(parts, _("Rented Serials"), self._rental_invoice_serial_summary())
        if self.requested_kva:
            add(parts, _("Requested kVA"), self.requested_kva)
        add(parts, _("Date Requested"), self.date_requested)
        add(parts, _("Planned Dispatch"), self.planned_dispatch_datetime)
        add(parts, _("Planned Install"), self.planned_install_datetime)
        add(parts, _("Planned Return"), self.planned_return_datetime)
        add(parts, _("Actual Dispatch"), self.actual_dispatch_datetime)
        add(parts, _("Actual Install"), self.actual_install_datetime)
        add(parts, _("Actual Return"), self.actual_return_datetime)
        if self.start_meter_reading:
            add(parts, _("Start Meter Reading"), self.start_meter_reading)
        if self.end_meter_reading:
            add(parts, _("End Meter Reading"), self.end_meter_reading)
        add(parts, _("Customer Receiver"), self.customer_receiver_name)
        add(parts, _("Dispatch Note"), self.dispatch_note)
        add(parts, _("Installation Note"), self.installation_note)
        add(parts, _("Return Note"), self.return_note)
        return '\n'.join(str(part) for part in parts if part)

    def _rental_invoice_line_name(self, line):
        self.ensure_one()
        asset = line.equipment_asset_id
        unit = line.item_unit_id
        title = (
            asset.display_name
            or unit.display_name
            or line.asset_display_name
            or _("Rented Serial"))
        details = self._rental_invoice_equipment_details(asset=asset, unit=unit)
        if not details and line.asset_serial_number:
            details.append(_("Serial Number: %s") % line.asset_serial_number)
        if line.specification:
            details.append(_("Specifications: %s") % line.specification)
        if line.is_free:
            details.append(_("Free of Charge"))
        return '\n'.join([title] + details)

    def _rental_invoice_line_income_account(self, line):
        self.ensure_one()
        product = self.env['product.product']
        if line.equipment_asset_id and line.equipment_asset_id.product_id:
            product = line.equipment_asset_id.product_id
        elif self.contract_id:
            product = self.contract_id.line_ids.filtered('product_id')[:1].product_id
        if not product:
            return self.env['account.account']
        accounts = product.product_tmpl_id.with_company(
            self.company_id).get_product_accounts()
        return accounts.get('income')

    def _rental_invoice_line_commands(self):
        self.ensure_one()
        tax = self._get_rental_invoice_tax()
        tax_cmd = [(6, 0, tax.ids)] if tax else False
        commands = []

        analytic = (
            self.analytic_account_id
            or (self.contract_id.analytic_account_id if self.contract_id else False)
        )
        has_analytic_distribution = (
            'analytic_distribution' in self.env['account.move.line']._fields)
        for line in self._rental_invoice_source_lines():
            account = self._rental_invoice_line_income_account(line)
            vals = {
                'name': self._rental_invoice_line_name(line),
                'rental_asset_type': line.asset_type_display_name,
                'rental_equipment_reference':
                    self._rental_invoice_equipment_reference(
                        asset=line.equipment_asset_id,
                        unit=line.item_unit_id),
                'quantity': line.quantity_days or 1.0,
                'price_unit': 0.0 if line.is_free else (line.daily_rate or 0.0),
            }
            if account:
                vals['account_id'] = account.id
            if tax_cmd:
                vals['tax_ids'] = tax_cmd
            if analytic and has_analytic_distribution:
                vals['analytic_distribution'] = {str(analytic.id): 100.0}
            commands.append((0, 0, vals))
        return commands

    def _draft_rental_invoice_to_update(self):
        self.ensure_one()
        draft_invoices = self.invoice_ids.filtered(
            lambda move: move.move_type == 'out_invoice'
            and move.state == 'draft')
        return draft_invoices.sorted('id')[:1]

    def action_create_invoice(self):
        self.ensure_one()
        if self.state not in self._INVOICEABLE_STATES:
            raise UserError(_(
                "Confirm the rental order before creating an invoice."))

        logs = self._billable_hour_logs()
        if not logs:
            invoice = self._create_manual_rental_invoice()
            self.invalidate_recordset([
                'invoice_ids', 'invoice_count', 'billable_log_count'])
            return self.action_view_invoices(invoices=invoice)

        dates = logs.mapped('reading_date')
        billing_run = self.env['gr.billing.run'].create({
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'rental_order_id': self.id,
            'date_from': min(dates),
            'date_to': max(dates),
            'note': _("Created from rental order %s.") % self.name,
        })
        billing_run.action_generate()
        self.invalidate_recordset([
            'invoice_ids', 'invoice_count', 'billable_log_count'])
        return self.action_view_invoices(invoices=billing_run.invoice_ids)

    def _create_manual_rental_invoice(self):
        self.ensure_one()
        lines = self._rental_invoice_line_commands()
        invoice = self._draft_rental_invoice_to_update()
        vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'currency_id': self.company_id.currency_id.id,
            'invoice_origin': self.name,
            'rental_order_id': self.id,
            'company_id': self.company_id.id,
            'invoice_line_ids': lines,
            'narration': _("Created from rental order %s.") % self.name,
        }
        if self.site_id and self.site_id.partner_id:
            vals['partner_shipping_id'] = self.site_id.partner_id.id
        if self.contract_id.payment_terms_id:
            vals['invoice_payment_term_id'] = self.contract_id.payment_terms_id.id
        if invoice:
            vals['invoice_line_ids'] = [(5, 0, 0)] + lines
            invoice.write(vals)
            return invoice
        return self.env['account.move'].with_context(
            default_move_type='out_invoice').create(vals)

    @api.readonly
    def action_view_invoices(self, invoices=False):
        self.ensure_one()
        invoices = invoices or self.invoice_ids
        action = self.env['ir.actions.actions']._for_xml_id(
            'account.action_move_out_invoice_type')

        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref('account.view_move_form').id, 'form')]
            action['views'] = form_view + [
                (view_id, view_type)
                for view_id, view_type in action.get('views', [])
                if view_type != 'form'
            ]
            action['res_id'] = invoices.id
        else:
            return {'type': 'ir.actions.act_window_close'}

        action['context'] = {
            'default_move_type': 'out_invoice',
            'default_partner_id': self.partner_id.id,
            'default_company_id': self.company_id.id,
            'default_invoice_origin': self.name,
            'default_rental_order_id': self.id,
        }
        return action
