from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    contact_limit = fields.Integer(
        string="Contact Limit",
        config_parameter='email_validation.contact_limit',
        default=500
    )
    batch = fields.Char(string="Batch", config_parameter='email_validation.batch')
    validation_state = fields.Selection([
        ('pending', 'Pending'),
        ('valid', 'Valid'),
        ('invalid', 'Invalid'),
        ('error', 'Error')
    ], default='pending', config_parameter='email_validation.state')
