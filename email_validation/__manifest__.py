{
    'name': 'Partner Email Validation',
    'version': '19.0.0.0.4',
    'license': 'LGPL-3',
    'category': 'Tools',
    'summary': 'Validate partner email addresses using regex.',
    'description': """
        This module adds a validation to ensure that partner email addresses are in a valid format using regular expressions.
    """,
    'author': 'Nians',
    'depends': ['base', 'contacts', 'hr'],
    'data': [
        # Add any XML files for views, security, etc. if needed
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/res_config_settings.xml',
        "views/web_domain.xml",
        'data/ir_cron.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
