# -*- coding: utf-8 -*-
{
    'name': 'AI Assistant for Odoo',
    'version': '17.0.1.0.4',
    'summary': 'Chat with your Odoo data in plain language. Cloud AI or your own local LLM (Ollama).',
    'description': """
AI Assistant for Odoo
=====================

A floating AI chat inside Odoo that turns plain-language questions into safe,
read-only queries and answers with text, tables, charts and CSV export.

* Works with any installed module: Sales, CRM, HR, Accounting, Inventory, custom apps
* Read-only: only search_count, search_read and read_group, run with the user's own access rights
* AI providers: OpenAI, Anthropic Claude, Google Gemini, Groq, and local open-source
  models through Ollama or any OpenAI-compatible server (LM Studio, vLLM, llama.cpp)
* Local models keep all data on your own network
* Bar, line and pie charts (Chart.js bundled, works offline) and CSV export
* Conversation history and per-user module access control

Developed by Faridullah Qaderi (Faridullahqaderi54@gmail.com)
Powered by FOITECH-Digital Solutions - https://www.foitech.com
Contact / WhatsApp: (+93) 788 70 74 79
    """,
    'author': 'Faridullah Qaderi - FOITECH-Digital Solutions',
    'maintainer': 'Faridullah Qaderi <Faridullahqaderi54@gmail.com>',
    'website': 'https://www.foitech.com',
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'external_dependencies': {'python': ['requests']},
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
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
