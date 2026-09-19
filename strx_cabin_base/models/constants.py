# -*- coding: utf-8 -*-
"""Single source of truth for the cabin readiness state machine.

These states are EVENT-DRIVEN: they are set by module logic (allocation, dispatch,
return, inspection…), never typed by users. The field is readonly in every view and
the underlying value is validated / logged server-side (see stock_lot.py).
"""

# Order matters: this is roughly the lifecycle order and is reused verbatim by
# both stock.lot.strx_readiness_state and strx.cabin.readiness.log.
READINESS_STATES = [
    ('available', 'Available'),
    ('held', 'Held'),
    ('reserved', 'Reserved'),
    ('allocated', 'Allocated'),
    ('staged', 'Staged'),
    ('dispatched', 'Dispatched'),
    ('on_rent', 'On Rent'),
    ('return_due', 'Return Due'),
    ('returned', 'Returned'),
    ('in_inspection', 'In Inspection'),
    ('in_cleaning', 'In Cleaning'),
    ('in_maintenance', 'In Maintenance'),
    ('damaged', 'Damaged'),
    ('retired', 'Retired'),
]

# Physical condition is deliberately separate from operational readiness.  A
# cabin may, for example, be in Fair condition and still be Available, or be in
# Good condition while temporarily In Cleaning.
CABIN_CONDITIONS = [
    ('new', 'New'),
    ('good', 'Good'),
    ('fair', 'Fair'),
    ('damaged', 'Damaged'),
]

# States hidden ENTIRELY from selection lists (client requirement).
HIDDEN_FROM_SELECTION = {'damaged', 'retired'}

# States that remain VISIBLE in selection lists but are NOT selectable —
# shown colour-coded (red/amber) and Arabic-labelled by the selection widgets.
VISIBLE_NOT_SELECTABLE = {'on_rent', 'in_maintenance'}

# The only state from which a unit is offerable to a new rental.
SELECTABLE_STATES = {'available'}

# States a unit passes through after coming back before it may return to 'available'.
# A returned cabin cannot become Available until inspection AND cleaning both pass.
POST_RETURN_STATES = {'returned', 'in_inspection', 'in_cleaning'}
