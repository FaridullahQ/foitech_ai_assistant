# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Replace retired Groq models stored in system parameters."""
    cr.execute("""
        UPDATE ir_config_parameter
           SET value = 'llama-3.1-8b-instant'
         WHERE key = 'odoo_ai.groq_model'
           AND value IN ('llama3-8b-8192', 'llama3-70b-8192',
                         'mixtral-8x7b-32768', 'gemma2-9b-it')
    """)
