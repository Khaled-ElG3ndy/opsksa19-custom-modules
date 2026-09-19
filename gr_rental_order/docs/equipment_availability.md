# Equipment Availability

This Odoo 19 implementation keeps two questions separate:

- `gr.generator.asset.status` describes the unit's current operational position.
- `gr.rental.availability` decides whether a physical unit can be booked for a requested date/time range.

The availability engine is the central service for rental commitments. It checks:

- primary `gr.rental.order.asset_id`
- all `gr.rental.order.line.equipment_asset_id` serials
- legacy `gr.rental.item.unit` lines
- confirmed/reserved/active rental orders using half-open datetime overlap
- scheduled and in-progress maintenance windows
- third-party supplier agreement windows
- hard unavailable statuses such as maintenance, breakdown, retired, unavailable, and pending inspection
- company isolation

Confirmed rental orders are treated as reservations. A future reservation does not overwrite the equipment's current status or current-customer fields; those fields are updated only when the rental is current/started by the workflow.

Use `env['gr.rental.availability']` for new code. Do not add new status-only double-booking checks.
