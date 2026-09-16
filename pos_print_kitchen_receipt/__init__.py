# Copyright 2026 Khaled ElGendy
# All rights reserved.

from odoo import release, _
from odoo.exceptions import UserError

from . import models


def pre_init_check(env):
    """Prevent accidental installation on an unsupported Odoo series."""
    if release.version_info[0] != 19:
        raise UserError(
            _(
                "POS Kitchen Receipt supports Odoo 19.0; server series %s was found.",
                release.series,
            )
        )

