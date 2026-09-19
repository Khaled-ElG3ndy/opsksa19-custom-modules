# -*- coding: utf-8 -*-
from math import ceil

from odoo import api, fields, _, models


class GrRentalOrderApproval(models.Model):
    """[1] The rental order / contract."""
    _name = 'gr.rental.order'
    _inherit = ['gr.rental.order', 'gr.customer.approval.mixin']

    def _get_approval_partner(self):
        self.ensure_one()
        return self.partner_id

    def _approval_document_label(self):
        self.ensure_one()
        return _("Rental order %s") % self.name

    def _approval_report_type(self):
        return 'rental_order'

    def _approval_pricing_data(self):
        self.ensure_one()
        contract = self.contract_id
        if not contract:
            return {
                'method': '', 'rate': 0.0, 'rate_label': '',
                'duration': _('Based on actual usage'), 'quantity': 0.0,
                'estimated_total': 0.0,
            }

        contract_type = contract.contract_type
        rate_map = {
            'hourly': (contract.hourly_rate, _('Hourly Rate')),
            'daily_with_included_hours': (
                contract.base_daily_rate, _('Base Daily Rate')),
            'monthly_with_included_hours': (
                contract.base_monthly_rate, _('Base Monthly Rate')),
            'standby_plus_usage': (contract.standby_rate, _('Standby Rate')),
        }
        rate, rate_label = rate_map.get(contract_type, (0.0, _('Base Rate')))
        method = dict(contract._fields['contract_type']._description_selection(
            contract.env)).get(contract_type, contract_type or '')

        start = self.planned_install_datetime or contract.date_start
        end = self.planned_return_datetime or contract.date_end
        days = 0
        if start and end:
            start_date = fields.Date.to_date(start)
            end_date = fields.Date.to_date(end)
            days = max((end_date - start_date).days, 1)

        quantity = 0.0
        if contract_type == 'hourly':
            quantity = max(
                (self.end_meter_reading or 0.0)
                - (self.start_meter_reading or 0.0), 0.0)
            duration = _('%(count)s hour(s)', count=quantity) \
                if quantity else _('Based on actual usage')
        elif contract_type == 'monthly_with_included_hours':
            quantity = ceil(days / 30.0) if days else 0.0
            duration = _('%(count)s month(s)', count=int(quantity)) \
                if quantity else _('Based on actual usage')
        else:
            quantity = days
            duration = _('%(count)s day(s)', count=int(quantity)) \
                if quantity else _('Based on actual usage')

        return {
            'method': method,
            'rate': rate,
            'rate_label': rate_label,
            'duration': duration,
            'quantity': quantity,
            'estimated_total': rate * quantity if rate and quantity else 0.0,
        }

    def _legacy_report_filename(self, report_kind, lang=None):
        self.ensure_one()
        lang = lang or self.env.context.get('lang') or self.env.lang
        env = self.with_context(lang=lang).env if lang else self.env
        if report_kind == 'delivery_note':
            name = env._('Delivery_Note')
        elif report_kind == 'installation':
            name = env._('Installation_Report')
        else:
            name = env._('Return_Inspection')
        return '%s_%s.pdf' % (name, self._document_filename_reference())

    def _approval_core_fields(self):
        return {
            'partner_id', 'site_id', 'contract_id', 'asset_id', 'requested_kva',
            'date_requested', 'planned_dispatch_datetime',
            'planned_install_datetime', 'planned_return_datetime',
            'dispatch_note', 'installation_note', 'return_note',
            'customer_receiver_name', 'item_line_ids', 'checklist_ids',
        }

    def _approval_content_payload(self):
        self.ensure_one()
        contract = self.contract_id
        asset = self.asset_id
        return {
            'name': self.name,
            'company': self.company_id.id,
            'partner': self.partner_id.id,
            'site': self.site_id.id,
            'contract': contract.id,
            'asset': {
                'id': asset.id, 'name': asset.display_name,
                'serial': asset.serial_number,
            } if asset else False,
            'requested_kva': self.requested_kva,
            'date_requested': self.date_requested,
            'planned_dispatch': self.planned_dispatch_datetime,
            'planned_install': self.planned_install_datetime,
            'planned_return': self.planned_return_datetime,
            'notes': [self.dispatch_note, self.installation_note, self.return_note],
            'contract_terms': {
                'date_start': contract.date_start,
                'date_end': contract.date_end,
                'contract_type': contract.contract_type,
                'base_daily_rate': contract.base_daily_rate,
                'base_monthly_rate': contract.base_monthly_rate,
                'hourly_rate': contract.hourly_rate,
                'included_hours_per_day': contract.included_hours_per_day,
                'max_hours_per_day': contract.max_hours_per_day,
                'overtime_hour_rate': contract.overtime_hour_rate,
                'violation_hour_rate': contract.violation_hour_rate,
                'standby_rate': contract.standby_rate,
                'operator_daily_rate': contract.operator_daily_rate,
                'fuel_billing_policy': contract.fuel_billing_policy,
                'fuel_rate': contract.fuel_rate,
                'mobilization_charge': contract.mobilization_charge,
                'demobilization_charge': contract.demobilization_charge,
                'security_deposit': contract.security_deposit,
                'terms': contract.terms_and_conditions,
            } if contract else False,
            'items': [{
                'id': line.id,
                'type': line.asset_type_display_name,
                'unit': line.asset_display_name,
                'serial': line.asset_serial_number,
                'specification': line.specification,
                'is_free': line.is_free,
                'daily_rate': line.daily_rate,
                'days': line.quantity_days,
                'total': line.line_total,
            } for line in self.item_line_ids.sorted('sequence')],
            'checklist': [{
                'phase': line.phase, 'name': line.name,
                'done': line.is_done, 'notes': line.notes,
            } for line in self.checklist_ids.sorted('id')],
        }

    def action_confirm(self):
        for order in self:
            order._require_customer_approval(_("confirming the rental order"))
        return super().action_confirm()


class GrRentalContractReportHelper(models.Model):
    _name = 'gr.rental.contract'
    _inherit = ['gr.rental.contract', 'gr.document.report.helper']

    def _approval_report_status_label(self):
        self.ensure_one()
        return dict(self._fields['state']._description_selection(
            self.env)).get(self.state, self.state or '')

    def _rental_contract_filename(self, lang=None):
        self.ensure_one()
        lang = lang or self.env.context.get('lang') or self.env.lang
        env = self.with_context(lang=lang).env if lang else self.env
        prefix = env._('Rental_Contract')
        return '%s_%s.pdf' % (
            prefix, self._document_filename_reference())


class GrRentalInspectionApproval(models.Model):
    """[2] Delivery of the asset, and [4] the return record.
    Both are gr.rental.inspection records (mode = delivery / return)."""
    _name = 'gr.rental.inspection'
    _inherit = ['gr.rental.inspection', 'gr.customer.approval.mixin']

    def _get_approval_partner(self):
        self.ensure_one()
        return self.partner_id

    def _approval_document_label(self):
        self.ensure_one()
        modes = dict(self._fields['mode'].selection)
        return _("%(mode)s note %(name)s",
                 mode=modes.get(self.mode, self.mode), name=self.name)

    def _approval_report_type(self):
        self.ensure_one()
        return 'return' if self.mode == 'return' else 'delivery'

    def _approval_core_fields(self):
        return {
            'rental_order_id', 'mode', 'inspection_date', 'current_hours',
            'checklist_ids', 'inspected_by_id', 'customer_ack_name', 'remarks',
        }

    def _approval_content_payload(self):
        self.ensure_one()
        order = self.rental_order_id
        asset = self.asset_id
        return {
            'name': self.name,
            'mode': self.mode,
            'order': order.id,
            'partner': self.partner_id.id,
            'site': order.site_id.id,
            'date': self.inspection_date,
            'hours': self.current_hours,
            'inspector': self.inspected_by_id.id,
            'customer_ack_name': self.customer_ack_name,
            'remarks': self.remarks,
            'asset': {
                'id': asset.id, 'name': asset.display_name,
                'serial': asset.serial_number,
            } if asset else False,
            'items': [{
                'id': line.id,
                'type': line.asset_type_display_name,
                'unit': line.asset_display_name,
                'serial': line.asset_serial_number,
                'specification': line.specification,
            } for line in order.item_line_ids.sorted('sequence')],
            'checklist': [{
                'name': line.name, 'result': line.result, 'note': line.note,
            } for line in self.checklist_ids.sorted('sequence')],
            'photos': [(photo.id, photo.checksum) for photo in self._approval_report_photos()],
        }

    def action_pass(self):
        for inspection in self:
            if inspection.mode == 'delivery':
                inspection._require_customer_approval(
                    _("passing the delivery document"))
            elif inspection.mode == 'return':
                inspection._require_customer_approval(
                    _("passing the return report"))
            else:
                inspection._require_customer_approval(
                    _("passing the inspection document"))
        return super().action_pass()


class GrFieldWorksheetApproval(models.Model):
    """[3] Every service visit report."""
    _name = 'gr.field.worksheet'
    _inherit = ['gr.field.worksheet', 'gr.customer.approval.mixin']

    def _get_approval_partner(self):
        self.ensure_one()
        return self.partner_id

    def _approval_document_label(self):
        self.ensure_one()
        return _("Visit report %s") % self.name

    def _approval_report_type(self):
        return 'visit'

    def _approval_core_fields(self):
        return {
            'job_id', 'inspection_id', 'asset_id', 'partner_id', 'contact_no',
            'project_name', 'location', 'hour_reading', 'time_in', 'time_out',
            'visiting_mode', 'voltage_vac', 'frequency_hz',
            'battery_voltage_dcv', 'oil_pressure_kpa', 'speed_rpm',
            'water_temp_c', 'load_5m', 'load_10m', 'load_15m',
            'checklist_ids', 'spare_part_ids', 'remarks', 'technician_id',
            'photo_ids', 'customer_ack_name',
        }

    def _approval_content_payload(self):
        self.ensure_one()
        asset = self.asset_id
        return {
            'name': self.name,
            'job': self.job_id.id,
            'inspection': self.inspection_id.id,
            'asset': {
                'id': asset.id, 'name': asset.display_name,
                'serial': asset.serial_number,
            } if asset else False,
            'partner': self.partner_id.id,
            'contact_no': self.contact_no,
            'project_name': self.project_name,
            'location': self.location,
            'hour_reading': self.hour_reading,
            'time_in': self.time_in,
            'time_out': self.time_out,
            'visiting_mode': self.visiting_mode,
            'readings': [
                self.voltage_vac, self.frequency_hz, self.battery_voltage_dcv,
                self.oil_pressure_kpa, self.speed_rpm, self.water_temp_c,
                self.load_5m, self.load_10m, self.load_15m,
            ],
            'technician': self.technician_id.id,
            'remarks': self.remarks,
            'customer_ack_name': self.customer_ack_name,
            'checklist': [{
                'name': line.name, 'result': line.result, 'note': line.note,
            } for line in self.checklist_ids.sorted('sequence')],
            'parts': [{
                'number': line.part_number, 'description': line.description,
                'quantity': line.quantity, 'remarks': line.remarks,
            } for line in self.spare_part_ids.sorted('id')],
            'photos': [(photo.id, photo.checksum) for photo in self.photo_ids.sorted('id')],
        }

    def action_verify(self):
        for worksheet in self:
            worksheet._require_customer_approval(_("verifying the visit report"))
        return super().action_verify()


class GrRentalOrderLineApproval(models.Model):
    _inherit = 'gr.rental.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        orders = self.env['gr.rental.order'].browse(
            [vals.get('order_id') for vals in vals_list if vals.get('order_id')])
        orders._approval_related_change_guard()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('order_id')._approval_related_change_guard()
        return super().write(vals)

    def unlink(self):
        self.mapped('order_id')._approval_related_change_guard()
        return super().unlink()


class GrRentalOrderChecklistApproval(models.Model):
    _inherit = 'gr.rental.order.checklist'

    @api.model_create_multi
    def create(self, vals_list):
        orders = self.env['gr.rental.order'].browse(
            [vals.get('order_id') for vals in vals_list if vals.get('order_id')])
        orders._approval_related_change_guard()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('order_id')._approval_related_change_guard()
        return super().write(vals)

    def unlink(self):
        self.mapped('order_id')._approval_related_change_guard()
        return super().unlink()


class GrRentalInspectionLineApproval(models.Model):
    _inherit = 'gr.rental.inspection.line'

    @api.model_create_multi
    def create(self, vals_list):
        inspections = self.env['gr.rental.inspection'].browse(
            [vals.get('inspection_id') for vals in vals_list if vals.get('inspection_id')])
        inspections._approval_related_change_guard()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('inspection_id')._approval_related_change_guard()
        return super().write(vals)

    def unlink(self):
        self.mapped('inspection_id')._approval_related_change_guard()
        return super().unlink()


class GrFieldWorksheetCheckApproval(models.Model):
    _inherit = 'gr.field.worksheet.check'

    @api.model_create_multi
    def create(self, vals_list):
        worksheets = self.env['gr.field.worksheet'].browse(
            [vals.get('worksheet_id') for vals in vals_list if vals.get('worksheet_id')])
        worksheets._approval_related_change_guard()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('worksheet_id')._approval_related_change_guard()
        return super().write(vals)

    def unlink(self):
        self.mapped('worksheet_id')._approval_related_change_guard()
        return super().unlink()


class GrFieldWorksheetPartApproval(models.Model):
    _inherit = 'gr.field.worksheet.part'

    @api.model_create_multi
    def create(self, vals_list):
        worksheets = self.env['gr.field.worksheet'].browse(
            [vals.get('worksheet_id') for vals in vals_list if vals.get('worksheet_id')])
        worksheets._approval_related_change_guard()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('worksheet_id')._approval_related_change_guard()
        return super().write(vals)

    def unlink(self):
        self.mapped('worksheet_id')._approval_related_change_guard()
        return super().unlink()
