# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import date, datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_datetime


class GrRentalAvailability(models.AbstractModel):
    """Central date-range availability service for rental equipment.

    Asset ``status`` still answers "where is the unit right now?".  This service
    answers the separate planning question: "can this unit be promised for this
    requested period?"  Keeping those questions apart is what allows future
    reservations without making today's operational status lie.
    """
    _name = 'gr.rental.availability'
    _description = 'Rental Availability Engine'

    _BLOCKING_ORDER_STATES = (
        'confirmed', 'reserved', 'dispatched', 'installed', 'on_rent',
        'off_hire_requested', 'returned', 'inspection',
    )
    _HARD_ASSET_STATUSES = (
        'maintenance_due', 'under_maintenance', 'breakdown', 'unavailable',
        'retired', 'returned_pending_inspection',
    )
    _HARD_ITEM_STATUSES = ('maintenance', 'unavailable', 'retired')
    _OPEN_END = datetime(9999, 12, 31, 23, 59, 59)

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------
    def _model_available(self, model_name):
        return model_name in self.env

    def _model(self, model_name):
        return self.env[model_name] if self._model_available(model_name) else False

    # ------------------------------------------------------------------
    # Date/range helpers
    # ------------------------------------------------------------------
    @api.model
    def _as_datetime(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        return fields.Datetime.to_datetime(value)

    @api.model
    def _explicit_order_start(self, order):
        order.ensure_one()
        return (
            self._as_datetime(order.actual_dispatch_datetime)
            or self._as_datetime(order.planned_dispatch_datetime)
            or self._as_datetime(order.actual_install_datetime)
            or self._as_datetime(order.planned_install_datetime)
            or self._as_datetime(order.date_requested)
        )

    @api.model
    def order_has_explicit_start(self, order):
        return bool(self._explicit_order_start(order))

    @api.model
    def _order_range(self, order):
        """Return the rental interval as ``(start, end)`` datetimes.

        ``end`` may be False, meaning open-ended.  Actuals win over planned
        dates, and a missing start falls back to the request/create date so an
        undated committed rental is still safely blocking.
        """
        order.ensure_one()
        start = (
            self._explicit_order_start(order)
            or self._as_datetime(order.create_date)
            or fields.Datetime.now()
        )
        end = (
            self._as_datetime(order.actual_return_datetime)
            or self._as_datetime(order.planned_return_datetime)
        )
        return start, end

    @api.model
    def _validate_range(self, start, end):
        if end and start and end < start:
            raise ValidationError(_(
                "The rental return date must be after the rental start date."))

    @api.model
    def _format_range(self, start, end):
        formatted_start = format_datetime(self.env, start) if start else _("not set")
        formatted_end = format_datetime(self.env, end) if end else _("open-ended")
        return _("%(start)s → %(end)s", start=formatted_start, end=formatted_end)

    @api.model
    def _end_for_sql(self, end):
        return end or self._OPEN_END

    @api.model
    def _date_for_supplier(self, value):
        return fields.Date.to_date(value) if value else False

    @api.model
    def _flush_order_sources(self):
        """Make recent ORM writes visible to the raw availability SQL."""
        self.env['gr.rental.order'].flush_model([
            'asset_id', 'state', 'company_id', 'name',
            'actual_dispatch_datetime', 'planned_dispatch_datetime',
            'actual_install_datetime', 'planned_install_datetime',
            'date_requested', 'create_date',
            'actual_return_datetime', 'planned_return_datetime',
        ])
        if self._model_available('gr.rental.order.line'):
            self.env['gr.rental.order.line'].flush_model([
                'order_id', 'equipment_asset_id', 'item_unit_id',
            ])

    @api.model
    def _flush_maintenance_sources(self):
        if not self._model_available('gr.maintenance.job'):
            return
        Job = self.env['gr.maintenance.job']
        fields_to_flush = [
            'asset_id', 'company_id', 'state', 'name', 'started_date',
            'scheduled_date', 'completed_date',
        ]
        if 'scheduled_end_datetime' in Job._fields:
            fields_to_flush.append('scheduled_end_datetime')
        Job.flush_model(fields_to_flush)

    # ------------------------------------------------------------------
    # Rental targets
    # ------------------------------------------------------------------
    @api.model
    def order_asset_ids(self, order):
        order.ensure_one()
        assets = self.env['gr.generator.asset']
        if order.asset_id:
            assets |= order.asset_id
        if 'item_line_ids' in order._fields:
            assets |= order.item_line_ids.mapped('equipment_asset_id')
        return assets

    @api.model
    def order_item_unit_ids(self, order):
        order.ensure_one()
        if 'item_line_ids' not in order._fields or not self._model_available('gr.rental.item.unit'):
            return self.env['ir.model'].browse()
        return order.item_line_ids.mapped('item_unit_id')

    @api.model
    def order_has_physical_targets(self, order):
        return bool(self.order_asset_ids(order) or self.order_item_unit_ids(order))

    @api.model
    def order_starts_now_or_past(self, order):
        start, _end = self._order_range(order)
        return not start or start <= fields.Datetime.now()

    # ------------------------------------------------------------------
    # Concurrency
    # ------------------------------------------------------------------
    @api.model
    def lock_assets(self, asset_ids):
        ids = sorted(set(asset_ids))
        if not ids:
            return
        self.env.cr.execute(
            """
            SELECT id
              FROM gr_generator_asset
             WHERE id = ANY(%s)
             ORDER BY id
             FOR UPDATE
            """,
            (ids,),
        )

    @api.model
    def lock_item_units(self, unit_ids):
        ids = sorted(set(unit_ids))
        if not ids or not self._model_available('gr.rental.item.unit'):
            return
        self.env.cr.execute(
            """
            SELECT id
              FROM gr_rental_item_unit
             WHERE id = ANY(%s)
             ORDER BY id
             FOR UPDATE
            """,
            (ids,),
        )

    # ------------------------------------------------------------------
    # Conflict collectors
    # ------------------------------------------------------------------
    @api.model
    def _asset_status_conflicts(self, assets):
        conflicts = []
        for asset in assets:
            if 'is_rentable' in asset._fields and not asset.is_rentable:
                if getattr(asset, 'owner_type', False) == 'customer_owned':
                    conflicts.append({
                        'type': 'ownership',
                        'category': 'unavailable',
                        'asset_id': asset.id,
                        'message': _(
                            "Equipment %(asset)s is customer-owned and cannot be rented out.",
                            asset=asset.display_name),
                    })
                else:
                    conflicts.append({
                        'type': 'ownership',
                        'category': 'unavailable',
                        'asset_id': asset.id,
                        'message': _(
                            "Equipment %(asset)s is not in the rental pool.",
                            asset=asset.display_name),
                    })
                continue
            if getattr(asset, 'maintenance_overdue', False):
                conflicts.append({
                    'type': 'maintenance',
                    'category': 'maintenance',
                    'asset_id': asset.id,
                    'message': _(
                        "Equipment %(asset)s has overdue maintenance and cannot be rented out.",
                        asset=asset.display_name),
                })
                continue
            if asset.status in self._HARD_ASSET_STATUSES:
                status_label = dict(asset._fields['status']._description_selection(
                    self.env)).get(asset.status, asset.status)
                category = 'maintenance' if asset.status in (
                    'maintenance_due', 'under_maintenance', 'breakdown') else 'unavailable'
                conflicts.append({
                    'type': 'status',
                    'category': category,
                    'asset_id': asset.id,
                    'message': _(
                        "Equipment %(asset)s is unavailable for the requested period "
                        "because its status is %(status)s.",
                        asset=asset.display_name, status=status_label),
                })
        return conflicts

    @api.model
    def _item_status_conflicts(self, units):
        conflicts = []
        if not units:
            return conflicts
        for unit in units:
            if unit.status in self._HARD_ITEM_STATUSES:
                status_label = dict(unit._fields['status']._description_selection(
                    self.env)).get(unit.status, unit.status)
                conflicts.append({
                    'type': 'status',
                    'category': 'unavailable',
                    'item_unit_id': unit.id,
                    'message': _(
                        "Item %(item)s is unavailable for the requested period "
                        "because its status is %(status)s.",
                        item=unit.display_name, status=status_label),
                })
        return conflicts

    @api.model
    def _order_conflicts_for_assets(self, asset_ids, start, end, company_id, exclude_order_id=False):
        if not asset_ids:
            return []
        self._flush_order_sources()
        end_limit = self._end_for_sql(end)
        exclude_order_id = exclude_order_id or 0
        states = list(self._BLOCKING_ORDER_STATES)
        conflicts = []

        query_params = (asset_ids, states, company_id, exclude_order_id, end_limit, start)
        self.env.cr.execute(
            """
            SELECT DISTINCT o.asset_id AS asset_id,
                   o.id AS order_id,
                   o.name AS order_name,
                   o.state AS state,
                   COALESCE(o.actual_dispatch_datetime,
                            o.planned_dispatch_datetime,
                            o.actual_install_datetime,
                            o.planned_install_datetime,
                            o.date_requested,
                            o.create_date) AS rental_start,
                   COALESCE(o.actual_return_datetime,
                            o.planned_return_datetime) AS rental_end
              FROM gr_rental_order o
             WHERE o.asset_id = ANY(%s)
               AND o.state = ANY(%s)
               AND o.company_id = %s
               AND o.id <> %s
               AND COALESCE(o.actual_dispatch_datetime,
                            o.planned_dispatch_datetime,
                            o.actual_install_datetime,
                            o.planned_install_datetime,
                            o.date_requested,
                            o.create_date) < %s
               AND COALESCE(o.actual_return_datetime,
                            o.planned_return_datetime,
                            TIMESTAMP '9999-12-31 23:59:59') > %s
            """,
            query_params,
        )
        primary_rows = self.env.cr.dictfetchall()

        line_rows = []
        if self._model_available('gr.rental.order.line'):
            self.env.cr.execute(
                """
                SELECT DISTINCT l.equipment_asset_id AS asset_id,
                       o.id AS order_id,
                       o.name AS order_name,
                       o.state AS state,
                       COALESCE(o.actual_dispatch_datetime,
                                o.planned_dispatch_datetime,
                                o.actual_install_datetime,
                                o.planned_install_datetime,
                                o.date_requested,
                                o.create_date) AS rental_start,
                       COALESCE(o.actual_return_datetime,
                                o.planned_return_datetime) AS rental_end
                  FROM gr_rental_order_line l
                  JOIN gr_rental_order o ON o.id = l.order_id
                 WHERE l.equipment_asset_id = ANY(%s)
                   AND o.state = ANY(%s)
                   AND o.company_id = %s
                   AND o.id <> %s
                   AND COALESCE(o.actual_dispatch_datetime,
                                o.planned_dispatch_datetime,
                                o.actual_install_datetime,
                                o.planned_install_datetime,
                                o.date_requested,
                                o.create_date) < %s
                   AND COALESCE(o.actual_return_datetime,
                                o.planned_return_datetime,
                                TIMESTAMP '9999-12-31 23:59:59') > %s
                """,
                query_params,
            )
            line_rows = self.env.cr.dictfetchall()

        assets = self.env['gr.generator.asset'].browse(asset_ids).exists()
        asset_by_id = {asset.id: asset for asset in assets}
        state_labels = dict(self.env['gr.rental.order']._fields['state']._description_selection(self.env))
        seen = set()
        for row in primary_rows + line_rows:
            key = (row['asset_id'], row['order_id'])
            if key in seen:
                continue
            seen.add(key)
            asset = asset_by_id.get(row['asset_id'])
            if not asset:
                continue
            conflicts.append({
                'type': 'order',
                'category': self._category_for_order_state(row['state']),
                'asset_id': row['asset_id'],
                'order_id': row['order_id'],
                'message': _(
                    "Equipment %(asset)s is already booked for %(order)s during "
                    "%(period)s (%(state)s).",
                    asset=asset.display_name,
                    order=row['order_name'],
                    period=self._format_range(row['rental_start'], row['rental_end']),
                    state=state_labels.get(row['state'], row['state'])),
            })
        return conflicts

    @api.model
    def _order_conflicts_for_item_units(self, unit_ids, start, end, company_id, exclude_order_id=False):
        if not unit_ids or not self._model_available('gr.rental.order.line'):
            return []
        self._flush_order_sources()
        end_limit = self._end_for_sql(end)
        exclude_order_id = exclude_order_id or 0
        self.env.cr.execute(
            """
            SELECT DISTINCT l.item_unit_id AS item_unit_id,
                   o.id AS order_id,
                   o.name AS order_name,
                   o.state AS state,
                   COALESCE(o.actual_dispatch_datetime,
                            o.planned_dispatch_datetime,
                            o.actual_install_datetime,
                            o.planned_install_datetime,
                            o.date_requested,
                            o.create_date) AS rental_start,
                   COALESCE(o.actual_return_datetime,
                            o.planned_return_datetime) AS rental_end
              FROM gr_rental_order_line l
              JOIN gr_rental_order o ON o.id = l.order_id
             WHERE l.item_unit_id = ANY(%s)
               AND o.state = ANY(%s)
               AND o.company_id = %s
               AND o.id <> %s
               AND COALESCE(o.actual_dispatch_datetime,
                            o.planned_dispatch_datetime,
                            o.actual_install_datetime,
                            o.planned_install_datetime,
                            o.date_requested,
                            o.create_date) < %s
               AND COALESCE(o.actual_return_datetime,
                            o.planned_return_datetime,
                            TIMESTAMP '9999-12-31 23:59:59') > %s
            """,
            (unit_ids, list(self._BLOCKING_ORDER_STATES), company_id,
             exclude_order_id, end_limit, start),
        )
        rows = self.env.cr.dictfetchall()
        Unit = self.env['gr.rental.item.unit']
        units = Unit.browse(unit_ids).exists()
        unit_by_id = {unit.id: unit for unit in units}
        state_labels = dict(self.env['gr.rental.order']._fields['state']._description_selection(self.env))
        conflicts = []
        for row in rows:
            unit = unit_by_id.get(row['item_unit_id'])
            if not unit:
                continue
            conflicts.append({
                'type': 'order',
                'category': self._category_for_order_state(row['state']),
                'item_unit_id': unit.id,
                'order_id': row['order_id'],
                'message': _(
                    "Item %(item)s is already booked for %(order)s during "
                    "%(period)s (%(state)s).",
                    item=unit.display_name,
                    order=row['order_name'],
                    period=self._format_range(row['rental_start'], row['rental_end']),
                    state=state_labels.get(row['state'], row['state'])),
            })
        return conflicts

    @api.model
    def _maintenance_conflicts(self, asset_ids, start, end, company_id):
        if not asset_ids or not self._model_available('gr.maintenance.job'):
            return []
        Job = self.env['gr.maintenance.job']
        self._flush_maintenance_sources()
        end_limit = self._end_for_sql(end)
        end_expr = (
            "COALESCE(j.completed_date, j.scheduled_end_datetime, "
            "TIMESTAMP '9999-12-31 23:59:59')"
            if 'scheduled_end_datetime' in Job._fields
            else "COALESCE(j.completed_date, TIMESTAMP '9999-12-31 23:59:59')"
        )
        self.env.cr.execute(
            """
            SELECT j.asset_id AS asset_id,
                   j.id AS job_id,
                   j.name AS job_name,
                   j.state AS state,
                   COALESCE(j.started_date, j.scheduled_date) AS maintenance_start,
                   {end_expr} AS maintenance_end
              FROM gr_maintenance_job j
             WHERE j.asset_id = ANY(%s)
               AND j.company_id = %s
               AND j.state IN ('scheduled', 'in_progress')
               AND COALESCE(j.started_date, j.scheduled_date) IS NOT NULL
               AND COALESCE(j.started_date, j.scheduled_date) < %s
               AND {end_expr} > %s
            """.format(end_expr=end_expr),
            (asset_ids, company_id, end_limit, start),
        )
        rows = self.env.cr.dictfetchall()
        assets = self.env['gr.generator.asset'].browse(asset_ids).exists()
        asset_by_id = {asset.id: asset for asset in assets}
        conflicts = []
        for row in rows:
            asset = asset_by_id.get(row['asset_id'])
            if not asset:
                continue
            conflicts.append({
                'type': 'maintenance',
                'category': 'maintenance',
                'asset_id': asset.id,
                'job_id': row['job_id'],
                'message': _(
                    "Equipment %(asset)s has maintenance %(job)s during %(period)s.",
                    asset=asset.display_name,
                    job=row['job_name'],
                    period=self._format_range(row['maintenance_start'], row['maintenance_end'])),
            })
        return conflicts

    @api.model
    def _supplier_conflicts(self, assets, start, end, company_id):
        if not assets or not self._model_available('gr.sublet.agreement'):
            return []
        Agreement = self.env['gr.sublet.agreement']
        rented_in = assets.filtered(lambda asset: getattr(asset, 'owner_type', False) == 'rented_in')
        if not rented_in:
            return []

        req_start = self._date_for_supplier(start)
        req_end = self._date_for_supplier(end)
        agreements = Agreement.search([
            ('asset_id', 'in', rented_in.ids),
            ('company_id', '=', company_id),
            ('state', 'in', ('draft', 'committed')),
        ], order='date_start desc, id desc')
        by_asset = defaultdict(lambda: Agreement)
        for agreement in agreements:
            by_asset[agreement.asset_id.id] |= agreement

        conflicts = []
        requested_period = self._format_range(start, end)
        for asset in rented_in:
            candidates = by_asset[asset.id]
            covering = candidates.filtered(
                lambda agreement: self._supplier_agreement_covers(
                    agreement, req_start, req_end, end))
            if covering:
                continue
            if not candidates:
                supplier = asset.owner_partner_id.display_name or _("the supplier")
                conflicts.append({
                    'type': 'supplier',
                    'category': 'unavailable',
                    'asset_id': asset.id,
                    'message': _(
                        "Equipment %(asset)s is Third-Party equipment rented from "
                        "%(supplier)s, but no supplier rental agreement covers "
                        "%(period)s.",
                        asset=asset.display_name,
                        supplier=supplier,
                        period=requested_period),
                })
                continue
            reference = candidates[:1]
            supplier_return = (
                fields.Date.to_string(reference.date_end)
                if reference and reference.date_end else _("open-ended"))
            conflicts.append({
                'type': 'supplier',
                'category': 'unavailable',
                'asset_id': asset.id,
                'message': _(
                    "Equipment %(asset)s is Third-Party equipment, but the requested "
                    "period %(period)s is outside its supplier rental period "
                    "(supplier return date: %(supplier_return)s).",
                    asset=asset.display_name,
                    period=requested_period,
                    supplier_return=supplier_return),
            })
        return conflicts

    @api.model
    def _supplier_agreement_covers(self, agreement, req_start, req_end, raw_end):
        if req_start and agreement.date_start and req_start < agreement.date_start:
            return False
        if agreement.date_end:
            if not raw_end:
                return False
            if req_end and req_end > agreement.date_end:
                return False
        return True

    @api.model
    def _category_for_order_state(self, state):
        if state in ('confirmed', 'reserved'):
            return 'reserved'
        if state in ('dispatched', 'installed', 'on_rent', 'off_hire_requested'):
            return 'rented'
        return 'unavailable'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @api.model
    def conflicts_for_targets(self, assets, start, end, company, exclude_order=False,
                              item_units=False):
        start = self._as_datetime(start)
        end = self._as_datetime(end)
        self._validate_range(start, end)
        company_id = company.id if hasattr(company, 'id') else company
        exclude_order_id = exclude_order.id if hasattr(exclude_order, 'id') else exclude_order
        if not isinstance(exclude_order_id, int):
            exclude_order_id = 0

        assets = assets.exists()
        if company_id:
            assets = assets.filtered(
                lambda asset: not asset.company_id
                or asset.company_id.id == company_id)
        item_units = item_units.exists() if item_units else item_units
        if item_units and company_id:
            item_units = item_units.filtered(
                lambda unit: not unit.company_id
                or unit.company_id.id == company_id)

        conflicts = []
        conflicts.extend(self._asset_status_conflicts(assets))
        conflicts.extend(self._item_status_conflicts(item_units))
        conflicts.extend(self._order_conflicts_for_assets(
            assets.ids, start, end, company_id, exclude_order_id=exclude_order_id))
        conflicts.extend(self._order_conflicts_for_item_units(
            item_units.ids if item_units else [], start, end, company_id,
            exclude_order_id=exclude_order_id))
        conflicts.extend(self._maintenance_conflicts(assets.ids, start, end, company_id))
        conflicts.extend(self._supplier_conflicts(assets, start, end, company_id))
        return conflicts

    @api.model
    def order_conflicts(self, order):
        order.ensure_one()
        start, end = self._order_range(order)
        assets = self.order_asset_ids(order)
        units = self.order_item_unit_ids(order)
        return self.conflicts_for_targets(
            assets, start, end, order.company_id, exclude_order=order,
            item_units=units)

    @api.model
    def assert_order_available(self, order, lock=False, exception='user'):
        order.ensure_one()
        start, end = self._order_range(order)
        self._validate_range(start, end)
        assets = self.order_asset_ids(order)
        units = self.order_item_unit_ids(order)
        if lock:
            self.lock_assets(assets.ids)
            self.lock_item_units(units.ids)
        conflicts = self.conflicts_for_targets(
            assets, start, end, order.company_id, exclude_order=order,
            item_units=units)
        if not conflicts:
            return True
        message = self.format_conflicts(conflicts)
        exc = ValidationError if exception == 'validation' else UserError
        raise exc(message)

    @api.model
    def assert_orders_available(self, orders, lock=False, exception='user'):
        for order in orders:
            self.assert_order_available(order, lock=lock, exception=exception)
        return True

    @api.model
    def format_conflicts(self, conflicts):
        lines = []
        seen = set()
        for conflict in conflicts:
            message = conflict.get('message')
            if not message or message in seen:
                continue
            seen.add(message)
            lines.append("- %s" % message)
        return _("Equipment is not available for the requested rental period:\n\n%s") \
            % "\n".join(lines)

    @api.model
    def order_availability_result(self, order):
        order.ensure_one()
        if not self.order_has_physical_targets(order):
            return {
                'state': 'not_ready',
                'message': _("Select rented serials to check availability."),
                'conflicts': [],
            }
        if not self.order_has_explicit_start(order):
            return {
                'state': 'not_ready',
                'message': _("Set a rental start date to check availability."),
                'conflicts': [],
            }
        try:
            conflicts = self.order_conflicts(order)
        except ValidationError as error:
            return {
                'state': 'unavailable',
                'message': str(error),
                'conflicts': [],
            }
        if conflicts:
            return {
                'state': 'unavailable',
                'message': self.format_conflicts(conflicts),
                'conflicts': conflicts,
            }
        start, end = self._order_range(order)
        return {
            'state': 'available',
            'message': _(
                "All selected rented serials are available for %(period)s.",
                period=self._format_range(start, end)),
            'conflicts': [],
        }

    @api.model
    def available_assets(self, start, end, company, domain=None, limit=None,
                         exclude_order=False):
        Asset = self.env['gr.generator.asset']
        company_id = company.id if hasattr(company, 'id') else company
        search_domain = [
            '|', ('company_id', '=', company_id), ('company_id', '=', False),
            ('active', '=', True),
        ]
        if 'is_rentable' in Asset._fields:
            search_domain.append(('is_rentable', '=', True))
        if domain:
            search_domain.extend(domain)
        assets = Asset.search(search_domain, limit=limit)
        if not assets:
            return assets
        conflicts = self.conflicts_for_targets(
            assets, start, end, company_id, exclude_order=exclude_order)
        blocked_ids = {conflict['asset_id'] for conflict in conflicts if conflict.get('asset_id')}
        return assets.filtered(lambda asset: asset.id not in blocked_ids)

    @api.model
    def availability_summary(self, start, end, company, domain=None):
        Asset = self.env['gr.generator.asset']
        company_id = company.id if hasattr(company, 'id') else company
        search_domain = [
            '|', ('company_id', '=', company_id), ('company_id', '=', False),
            ('active', '=', True),
        ]
        if 'is_rentable' in Asset._fields:
            search_domain.append(('is_rentable', '=', True))
        if domain:
            search_domain.extend(domain)
        assets = Asset.search(search_domain)
        conflicts = self.conflicts_for_targets(assets, start, end, company_id)
        categories = defaultdict(set)
        for conflict in conflicts:
            if conflict.get('asset_id'):
                categories[conflict.get('category', 'unavailable')].add(conflict['asset_id'])
        blocked = set().union(*categories.values()) if categories else set()
        return {
            'total': len(assets),
            'available': len(assets.filtered(lambda asset: asset.id not in blocked)),
            'reserved': len(categories['reserved']),
            'rented': len(categories['rented']),
            'maintenance': len(categories['maintenance']),
            'unavailable': len(categories['unavailable']),
        }
