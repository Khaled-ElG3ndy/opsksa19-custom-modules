# -*- coding: utf-8 -*-
{
    'name': "Generator Rental",
    'summary': "Security roles, record-rule base and root menu for the Generator Rental ERP",
    'description': """
Generator Rental ERP - Security Base
====================================
Foundation module for the generator-rental vertical (gr_* suite).

Provides:
  * Security category and the nine functional groups
    (User, Sales Officer, Operations Officer, Maintenance Technician,
     Maintenance Manager, Finance Officer, Finance Manager,
     General Manager, Administrator)
  * Group inheritance graph
  * Root application menu "Generator Rental ERP" and top-level submenus
    used by downstream modules.

M0 scaffold: groups + menu shells only. No business models.
""",
    'version': '19.0.1.2.0',
    'category': 'Industries/Rental',
    'author': 'Generator Rental ERP Project',
    'website': 'https://gen.getintakepilot.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/gr_security_groups.xml',
        'security/ir.model.access.csv',
        'data/gr_assign_admin.xml',
        'views/gr_menus.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
