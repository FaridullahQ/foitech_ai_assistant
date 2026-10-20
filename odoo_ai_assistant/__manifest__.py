# -*- coding: utf-8 -*-
{
    'name': 'AI Assistant for Odoo',
    'version': '17.0.1.0.1',
    'summary': 'Universal AI Assistant — Query any Odoo module via natural language',
    'description': """
        A floating AI chat assistant that allows users to query any installed Odoo module
        using natural language. Supports OpenAI (ChatGPT), Claude (Anthropic), and
        Google Gemini, and Groq. Features include conversation history, chart visualization,
        and Excel/CSV export of results.
    """,
    'author': 'FOI-TECH-Faridullah Qaderi',
    'website': 'https://www.foitech.com',
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/ai_chat_history_views.xml',
        'views/ai_user_access_views.xml',
        'views/menu_views.xml',
        'data/ir_config_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_ai_assistant/static/src/css/ai_assistant.css',
            'odoo_ai_assistant/static/src/js/ai_assistant.js',
            'odoo_ai_assistant/static/src/xml/ai_assistant.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': [],
}
