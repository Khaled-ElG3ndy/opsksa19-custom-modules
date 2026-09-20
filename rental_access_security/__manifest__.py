# -*- coding: utf-8 -*-
{
    'name': 'Rental Access Security',
    'version': '19.0.1.0.0',
    'summary': 'Shared Access Rights category for rental verticals.',
    'description': """
Rental Access Security
======================

Defines the shared "Rental Access" category used by independent rental
verticals so their access toggles appear under one section on the user form.
""",
    'author': 'OPS KSA',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Hidden',
    'depends': ['base'],
    'data': [
        'security/rental_access_category.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
