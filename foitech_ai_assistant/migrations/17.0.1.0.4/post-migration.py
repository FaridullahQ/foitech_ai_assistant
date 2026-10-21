# -*- coding: utf-8 -*-
"""Replace model ids that the providers have retired with current defaults."""


def migrate(cr, version):
    replacements = {
        'odoo_ai.openai_model': (
            ('gpt-3.5-turbo', 'gpt-4-turbo', 'gpt-4o-mini', 'gpt-4o'), 'gpt-5-mini'),
        'odoo_ai.claude_model': (
            ('claude-sonnet-4-20250514', 'claude-haiku-4-5-20251001'), 'claude-sonnet-5-5'),
        'odoo_ai.gemini_model': (
            ('gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash', 'gemini-2.5-flash'),
            'gemini-flash-latest'),
    }
    for key, (old_values, new_value) in replacements.items():
        cr.execute(
            "UPDATE ir_config_parameter SET value = %s WHERE key = %s AND value = ANY(%s)",
            (new_value, key, list(old_values)),
        )
