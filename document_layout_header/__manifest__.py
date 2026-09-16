# -*- coding: utf-8 -*-
{
    # App information
    'name': 'Document Layout Header',
    'category': '',
    'summary': 'Document Layout Header for the header and footer full image change in the pdf reports',
    'description': 'Document Layout Header for the header and footer full image change in the pdf reports',
    'version': '17.0.0.3',
    'author': "MP Technolabs",
    'license': 'LGPL-3',
    'website': "https://www.mptechnolabs.com",
    # Dependencies
    'depends': ['base', 'web'],

    # Data
    'data': [
        'views/inherit_base_document_layout.xml',
        'views/layout_template.xml',
    ],

    # Technical
    'installable': True,
    'auto_install': False,
    'application': False,
}
