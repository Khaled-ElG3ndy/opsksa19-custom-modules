# -*- coding: utf-8 -*-
import logging
from . import models

_logger = logging.getLogger(__name__)


def _configure_parts_category(env):
    """Configure the generator spare-parts category per company:
      - property_cost_method = 'average' (AVCO) so each part's cost auto-updates
        to the last purchase price on receipt;
      - property_valuation = 'real_time' (automated) where the company's
        accounting supports it.
    Both are company-dependent fields, so they are written via ORM with company
    context (not static XML).

    Robust by design:
      - the two writes are independent, so a valuation failure (which needs
        accounting setup) can never drop the cost-method write;
      - exceptions are caught narrowly per-write and logged, not swallowed
        wholesale;
      - idempotent: safe to run on install AND on upgrade.
    """
    category = env.ref('gr_parts_consumption.product_category_gr_parts',
                       raise_if_not_found=False)
    if not category:
        return
    for company in env['res.company'].search([]):
        cat = category.with_company(company)
        # 1) Costing method (AVCO). Does NOT require valuation accounts, so this
        #    should succeed on any company.
        try:
            if cat.property_cost_method != 'average':
                cat.property_cost_method = 'average'
        except Exception as e:  # pragma: no cover - defensive
            _logger.warning(
                "gr_parts_consumption: could not set AVCO cost method for "
                "company %s: %s", company.name, e)
        # 2) Automated valuation. Requires the company's stock valuation
        #    accounts; if not configured, leave as-is (manual) without failing.
        try:
            if cat.property_valuation != 'real_time':
                cat.property_valuation = 'real_time'
        except Exception as e:
            _logger.info(
                "gr_parts_consumption: automated valuation not set for company "
                "%s (accounting not fully configured): %s", company.name, e)


def post_init_configure_parts_category(env):
    """post_init_hook entry point (fires on uninstalled->installed)."""
    _configure_parts_category(env)
