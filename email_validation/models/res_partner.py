import re
import smtplib
import dns.resolver
import socket
import random
import string
from odoo.modules.module import get_module_path
import os

from concurrent.futures import ThreadPoolExecutor, as_completed

from odoo import models, fields, api

EMAIL_REGEX = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)

MX_CACHE = {}

ERROR_CODES = {
    250: "VALID_EMAIL",
    251: "FORWARDED_EMAIL",

    # TEMPORARY
    421: "SERVER_UNAVAILABLE",
    450: "MAILBOX_TEMP_UNAVAILABLE",
    451: "LOCAL_PROCESSING_ERROR",
    452: "INSUFFICIENT_SYSTEM_STORAGE",

    # PERMANENT
    550: "MAILBOX_NOT_FOUND",
    551: "USER_NOT_LOCAL",
    552: "MAILBOX_FULL",
    553: "INVALID_MAILBOX_NAME",
    554: "TRANSACTION_FAILED",
}

DISPOSABLE_DOMAINS = None


class ResPartner(models.Model):
    _inherit = 'res.partner'

    email_valid = fields.Boolean(
        string='Email Valid',
        default=False
    )

    batch = fields.Char(
        string='Batch'
    )

    validation_msg = fields.Text(
        string='Validation Message'
    )

    validation_state = fields.Selection([
        ('pending', 'Pending'),
        ('valid', 'Valid'),
        ('invalid', 'Invalid'),
        ('error', 'Error')
    ], default='pending')

    catch_all = fields.Boolean("Is Catchall Mail")

    first_name = fields.Char('First Name')
    last_name = fields.Char('Last Name')
    linked_in = fields.Char('LinkedIn')
    source = fields.Char('Source')

    @api.onchange('first_name', 'last_name')
    def _onchange_first_name_last_name(self):
        for rec in self:
            rec.name = ' '.join(filter(None, [rec.first_name, rec.last_name]))

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:

            if vals.get('email'):
                vals['email_valid'] = False
                vals['validation_msg'] = False
                vals['validation_state'] = 'pending'

        return super().create(vals_list)

    def write(self, vals):

        if 'email' in vals:
            vals['email_valid'] = False
            vals['validation_msg'] = False
            vals['validation_state'] = 'pending'

        return super().write(vals)

    def _get_mx_host(self, domain):

        domain = domain.strip().lower()

        if domain in MX_CACHE:
            return MX_CACHE[domain]

        resolver = dns.resolver.Resolver()

        # resolver.nameservers = [
        #     '8.8.8.8',  # Google
        #     '8.8.4.4'
        # ]

        resolver.timeout = 5
        resolver.lifetime = 5

        answers = resolver.resolve(domain, 'MX')

        mx_records = sorted([
            (
                r.preference,
                str(r.exchange).rstrip('.').lower()
            )
            for r in answers
        ])

        if not mx_records:
            return False

        mx_host = mx_records[0][1]
        MX_CACHE[domain] = mx_host

        return mx_host

    def smtp_check(self, email):

        try:
            email = (email or '').strip().lower()

            if not EMAIL_REGEX.match(email):
                return {
                    "success": False,
                    "state": "invalid",
                    "error_code": "INVALID_FORMAT",
                    "smtp_code": None,
                    "message": "Invalid email format"
                }

            domain = email.split('@')[1]

            try:
                if self._check_disposable_domain(domain):
                    self._store_domain(
                        domain,
                        disposable=True
                    )

                    return {
                        "success": False,
                        "state": "invalid",
                        "error_code": "DISPOSABLE_DOMAIN",
                        "smtp_code": None,
                        "message": "Disposable email domain detected"
                    }

            except Exception as e:
                pass

            try:

                mx_host = self._get_mx_host(domain)

                if not mx_host:
                    return {
                        "success": False,
                        "state": "invalid",
                        "error_code": "NO_MX_RECORD",
                        "smtp_code": None,
                        "message": "No MX records found"
                    }

            except dns.resolver.NXDOMAIN:

                return {
                    "success": False,
                    "state": "invalid",
                    "error_code": "DOMAIN_NOT_FOUND",
                    "smtp_code": None,
                    "message": "Domain does not exist"
                }

            except Exception as e:

                return {
                    "success": False,
                    "state": "error",
                    "error_code": "DNS_ERROR",
                    "smtp_code": None,
                    "message": str(e)
                }

            server = None

            try:

                server = smtplib.SMTP(timeout=45)

                server.connect(mx_host, 25)

                ehlo_code, ehlo_message = server.ehlo(
                    "technians.com"
                )

                if ehlo_code != 250:
                    return {
                        "success": False,
                        "state": "error",
                        "error_code": "EHLO_FAILED",
                        "smtp_code": ehlo_code,
                        "message": str(ehlo_message)
                    }

                mail_code, mail_message = server.mail("career@technians.com")

                if mail_code != 250:
                    return {
                        "success": False,
                        "state": "error",
                        "error_code": "MAIL_FROM_FAILED",
                        "smtp_code": mail_code,
                        "message": str(mail_message)
                    }

                code, message = server.rcpt(email)

                fake_email = self._generate_random_email(domain)

                try:
                    fake_code, fake_message = server.rcpt(fake_email)
                except Exception:
                    fake_code = None

                catch_all = False

                if code in [250, 251] and fake_code in [250, 251]:
                    catch_all = True

            finally:

                if server:

                    try:
                        server.quit()

                    except Exception:
                        pass

            message = (
                message.decode()
                if isinstance(message, bytes)
                else str(message)
            )

            error_code = ERROR_CODES.get(
                code,
                "UNKNOWN_SMTP_RESPONSE"
            )
            valid_codes = {250, 251}

            invalid_codes = {550, 551, 553}

            if code in valid_codes:

                success = True
                state = 'valid'

            elif code in invalid_codes:

                success = False
                state = 'invalid'

            else:

                success = False
                state = 'error'

            # store domain info
            try:
                if catch_all:
                    self._store_domain(domain, catch_all=True)
            except Exception:
                pass

            return {

                "success": success,

                "state": state,

                "error_code": error_code,

                "smtp_code": code,

                "message": message,
                "catch_all": catch_all
            }


        except socket.timeout:

            return {

                "success": False,

                "state": "error",

                "error_code": "CONNECTION_TIMEOUT",

                "smtp_code": None,

                "message": "SMTP connection timeout"
            }

        except OSError as e:

            error_message = str(e).lower()

            if "timed out" in error_message:

                error_code = "PORT_BLOCKED_OR_TIMEOUT"

            elif "network is unreachable" in error_message:

                error_code = "NETWORK_UNREACHABLE"

            elif "10054" in error_message:

                error_code = "REMOTE_SERVER_CLOSED_CONNECTION"

            elif "getaddrinfo failed" in error_message:

                error_code = "INVALID_HOSTNAME"

            else:

                error_code = "OS_ERROR"

            return {

                "success": False,

                "state": "error",

                "error_code": error_code,

                "smtp_code": None,

                "message": str(e)
            }

        except Exception as e:

            return {

                "success": False,

                "state": "error",

                "error_code": "UNKNOWN_ERROR",

                "smtp_code": None,

                "message": str(e)
            }

    def action_validate_email(self):

        for partner in self:

            if not partner.email:
                partner.sudo().write({

                    'email_valid': False,

                    'validation_state': 'invalid',

                    'validation_msg': 'Email missing'
                })

                continue

            result = self.smtp_check(partner.email)

            partner.sudo().write({

                'email_valid': result['success'],

                'validation_state': result['state'],

                'validation_msg': (
                    f"{result['error_code']} | "
                    f"{result['message']}"
                ),
                'catch_all': result.get('catch_all', False),
            })

    def _validate_partner_email_thread(self, email, partner_id):

        try:

            result = self.smtp_check(email)

            return {

                'partner_id': partner_id,

                'success': result['success'],

                'message': (
                    f"{result['message']}"
                ),
                'error_code': result['error_code'],

                'state': result['state'],
                'catch_all': result.get('catch_all', False)
            }

        except Exception as e:

            return {

                'partner_id': partner_id,

                'success': False,

                'message': str(e),
                'error_code': 'UNKNOWN_ERROR',

                'state': 'error',
                'catch_all': False,
            }

    @api.model
    def cron_validate_partner_emails(self):

        config = self.env['ir.config_parameter'].sudo()

        limit = int(
            config.get_param(
                'email_validation.contact_limit',
                default=500
            )
        )

        batch = config.get_param(
            'email_validation.batch',
            default=False
        )

        validation_state = config.get_param(
            'email_validation.state',
            default='pending'
        )

        domain = [
            ('email', '!=', False),
            ('validation_state', '=', f'{validation_state}'),
        ]

        if batch:
            domain.append(
                ('batch', '=', batch)
            )

        partners = self.sudo().search(
            domain,
            limit=limit
        )

        if not partners:
            return

        with ThreadPoolExecutor(max_workers=5) as executor:

            futures = {

                executor.submit(
                    self._validate_partner_email_thread,
                    partner.email,
                    partner.id
                ): partner.id

                for partner in partners
            }

            for future in as_completed(futures):

                try:

                    result = future.result()

                    partner = self.env[
                        'res.partner'
                    ].sudo().browse(
                        result['partner_id']
                    ).exists()

                    if not partner:
                        continue

                    partner.sudo().write({

                        'email_valid': result['success'],
                        'validation_state': result['state'],
                        'validation_msg': f"{result['error_code']} | "
                                          f"{result['message']}",

                    })

                    self.env.cr.commit()

                except Exception:
                    pass

    def _generate_random_email(self, domain):
        rand = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        return f"{rand}@{domain}"

    def _store_domain(self, domain, catch_all=False, disposable=False):
        Domain = self.env['web.domain'].sudo()

        existing = Domain.search([('name', '=', domain)], limit=1)

        if existing:
            vals = {}
            if catch_all and not existing.is_catchall:
                vals['is_catchall'] = True
            if disposable and not existing.is_disposable:
                vals['is_disposable'] = True

            if vals:
                existing.write(vals)
        else:
            Domain.create({
                'name': domain,
                'is_catchall': catch_all,
                'is_disposable': disposable
            })

    def _load_disposable_domains(self):
        global DISPOSABLE_DOMAINS

        if DISPOSABLE_DOMAINS is None:
            module_path = get_module_path('email_validation')

            file_path = os.path.join(
                module_path,
                'data',
                'disposable_email_blocklist.conf'
            )

            with open(file_path, 'r', encoding='utf-8') as f:
                DISPOSABLE_DOMAINS = {
                    line.strip().lower()
                    for line in f
                    if line.strip()
                       and not line.startswith('#')
                }

        return DISPOSABLE_DOMAINS

    def _check_disposable_domain(self, domain):
        domains = self._load_disposable_domains()
        return domain.lower() in domains
