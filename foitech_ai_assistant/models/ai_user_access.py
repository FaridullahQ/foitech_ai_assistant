# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AIUserModuleAccess(models.Model):
    """
    Stores per-user module restrictions for the AI Assistant.
    If NO record exists for a user → full access to all modules (default).
    If a record exists → only allowed_module_ids are accessible.
    Administrators (base.group_system) always bypass this — full access always.
    """
    _name = 'odoo.ai.user.access'
    _description = 'AI Assistant User Module Access'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        ondelete='cascade', index=True,
        domain=[('share', '=', False)],   # internal users only
    )
    allowed_module_ids = fields.Many2many(
        'ir.module.module',
        'odoo_ai_user_access_module_rel',
        'access_id', 'module_id',
        string='Allowed Modules',
        domain=[('state', '=', 'installed')],
    )
    is_super_user = fields.Boolean(
        string='AI Super User',
        default=False,
        help='If enabled, this user has unrestricted access to ALL modules in the '
             'AI Assistant, regardless of the allowed modules list below.',
    )
    note = fields.Char(string='Note', help='Optional description for this access rule')

    _sql_constraints = [
        ('user_unique', 'UNIQUE(user_id)', 'An access rule already exists for this user.'),
    ]

    @api.model
    def get_allowed_models_for_user(self, user_id=None):
        """
        Priority order:
        1. Odoo Administrator (group_system)  → unrestricted
        2. AI Super User checkbox = True      → unrestricted
        3. No rule defined for user           → unrestricted (default open)
        4. Rule defined, not super            → restricted to allowed_module_ids
        5. Rule defined, no modules selected  → fully blocked
        """
        if user_id is None:
            user_id = self.env.uid

        user = self.env['res.users'].browse(user_id)

        # 1. Odoo Administrators bypass everything
        if user.has_group('base.group_system'):
            return None

        access_rule = self.search([('user_id', '=', user_id)], limit=1)

        # 3. No rule at all → full access
        if not access_rule:
            return None

        # 2. AI Super User flag → full access
        if access_rule.is_super_user:
            return None

        # 4 & 5. Restricted to allowed modules
        allowed_modules = access_rule.allowed_module_ids
        if not allowed_modules:
            return set()  # blocked — rule exists but nothing selected

        models_in_modules = self.env['ir.model'].sudo().search([
            ('modules', 'in', allowed_modules.mapped('name')),
        ])
        return set(models_in_modules.mapped('model'))
