# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Dashboards",
    'summary': "Native pivot/graph/kanban dashboards: fleet, revenue, "
               "maintenance, and (live) asset profitability",
    'description': "Dashboards (gr_dashboard): role-oriented native Odoo "
                   "pivot/graph/kanban/list views over the existing data - fleet "
                   "utilization & status, revenue & billing (overtime/violation), "
                   "maintenance (overdue/breakdowns/jobs), and asset "
                   "profitability. Computes each asset's live utilization (from "
                   "approved hour logs) and revenue (from generated invoices). "
                   "Cost is labor-only until the parts-consumption milestone, "
                   "after which profitability is fully accurate. Read-only "
                   "aggregation - no new write paths. Part of the Generator "
                   "Rental ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.5',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_rental_order',
                'gr_hour_log', 'gr_billing', 'gr_maintenance', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/gr_dashboard_data.xml',
        'views/gr_dashboard_fleet_views.xml',
        'views/gr_dashboard_revenue_views.xml',
        'views/gr_dashboard_maintenance_views.xml',
        'views/gr_dashboard_profitability_views.xml',
        'views/gr_dashboard_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gr_dashboard/static/src/scss/gr_dashboard.scss',
        ],
    },
    'application': False,
    'installable': True,
    'auto_install': False,
}
