# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OdooAIChatHistory(models.Model):
    _name = 'odoo.ai.chat.history'
    _description = 'AI Assistant Chat History'
    _order = 'create_date desc'
    _rec_name = 'prompt'

    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    prompt = fields.Text(string='Question', required=True)
    answer = fields.Text(string='Answer', required=True)
    query_type = fields.Selection([
        ('odoo_query', 'Data Query'),
        ('general', 'General Question'),
        ('not_found', 'Not Found'),
    ], string='Query Type', default='odoo_query')
    create_date = fields.Datetime(string='Date', readonly=True)
