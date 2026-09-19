# -*- coding: utf-8 -*-
{
    'name': "Generator Rental ERP - Maintenance",
    'summary': "PM plans (hour/calendar/ad-hoc) and full maintenance work orders "
               "with assignee, scheduling, and status flow",
    'description': "Maintenance (gr.maintenance.job): full work orders for "
                   "preventive, corrective, and breakdown maintenance, with "
                   "assignee, scheduling, a draft->scheduled->in_progress->done "
                   "status flow, labor/downtime capture, and checklists. PM is "
                   "triggered by engine hours OR calendar days OR ad-hoc "
                   "(whichever first); a daily cron flags calendar-due assets. "
                   "Extends the generator asset with calendar-PM fields and folds "
                   "them into the maintenance-overdue flag. Completing a job "
                   "resets the PM clock and returns the asset to service; "
                   "breakdowns take it out of service immediately. Reusable PM "
                   "templates pre-fill standard checklists. Part of the Generator "
                   "Rental ERP vertical (gr_* suite) for Odoo 18 Community.",
    'version': '19.0.1.0.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['gr_security_base', 'gr_fleet_base', 'gr_rental_order', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/gr_maintenance_record_rules.xml',
        'data/ir_sequence.xml',
        'data/gr_maintenance_cron.xml',
        'views/gr_generator_asset_maintenance_views.xml',
        'views/gr_maintenance_template_views.xml',
        'views/gr_maintenance_job_views.xml',
        'views/gr_maintenance_menus.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
