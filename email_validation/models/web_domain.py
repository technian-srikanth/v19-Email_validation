from odoo import fields, models


class WebDomain(models.Model):
    _name = 'web.domain'
    _rec_name = 'name'

    name = fields.Char(string="Name")
    is_disposable = fields.Boolean(default=False)
    is_catchall = fields.Boolean(default=False)

    _sql_constraints = [
        ('domain_unique', 'unique(name)', 'Domain must be unique.')
    ]
