# -*- coding: utf-8 -*-
"""The OpenAI, Claude and Gemini model fields changed from Selection to Char.

Odoo keeps one ir.model.fields.selection row (plus an xmlid) per old dropdown
value. After the field becomes a Char, Odoo's end-of-upgrade cleanup tries to
read `field.ondelete` on those rows and crashes. Remove the leftovers first.
"""

FIELDS = (
    'odoo_ai_openai_model',
    'odoo_ai_claude_model',
    'odoo_ai_gemini_model',
)


def migrate(cr, version):
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE model = 'ir.model.fields.selection'
           AND res_id IN (
                SELECT s.id
                  FROM ir_model_fields_selection s
                  JOIN ir_model_fields f ON f.id = s.field_id
                 WHERE f.model = 'res.config.settings'
                   AND f.name IN %s)
    """, (FIELDS,))
    cr.execute("""
        DELETE FROM ir_model_fields_selection
         WHERE field_id IN (
                SELECT id FROM ir_model_fields
                 WHERE model = 'res.config.settings'
                   AND name IN %s)
    """, (FIELDS,))
