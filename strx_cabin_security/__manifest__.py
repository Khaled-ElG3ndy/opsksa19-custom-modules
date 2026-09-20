# -*- coding: utf-8 -*-
{
    'name': 'STRX Cabin Control — Security',
    'version': '19.0.1.1.1',
    'summary': 'Roles for the cabin-rental vertical, so cabin access is granted '
               'explicitly instead of riding on the generic Inventory and Sales roles.',
    'description': """
Cabin Control security
======================

Before this module every cabin model was reachable by anyone holding
``stock.group_stock_user`` or ``sales_team.group_sale_salesman``. In a shared
database that means the generator-rental staff would see the whole Cabin Control
application. This module introduces a dedicated role ladder so cabin access has
to be granted on purpose.

Separation works on two levels:

* **Functional** — every ``strx.*`` model is gated by the roles defined here, and
  every generator ``gr.*`` model is gated by ``gr_security_base`` roles. Neither
  side can reach the other's models without being given the role.
* **Data** — the models both businesses share (sales orders, transfers, invoices,
  partners, products) are separated by company through Odoo's multi-company
  record rules. A user only ever sees the companies listed on their user record.
""",
    'author': 'STRX',
    'website': 'https://ops-ksa.com',
    'license': 'LGPL-3',
    'category': 'Inventory/Inventory',
    'depends': ['base', 'stock', 'sales_team', 'rental_access_security'],
    'data': [
        'security/cabin_security_groups.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
