# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Provider Selection ──────────────────────────────────────
    odoo_ai_provider = fields.Selection([
        ('openai', 'OpenAI (ChatGPT)'),
        ('claude', 'Claude (Anthropic)'),
        ('gemini', 'Google Gemini'),
        ('groq',   'Groq — FREE (Llama3, no credit card)'),
    ], string='AI Provider', default='groq',
       config_parameter='odoo_ai.provider')

    # ── OpenAI ──────────────────────────────────────────────────
    odoo_ai_openai_api_key = fields.Char(
        string='OpenAI API Key',
        config_parameter='odoo_ai.openai_api_key',
    )
    odoo_ai_openai_model = fields.Selection([
        ('gpt-4o-mini', 'GPT-4o Mini (Free Tier / Default)'),
        ('gpt-4o', 'GPT-4o (Recommended)'),
        ('gpt-4-turbo', 'GPT-4 Turbo'),
        ('gpt-3.5-turbo', 'GPT-3.5 Turbo (Economy)'),
    ], string='OpenAI Model', default='gpt-4o-mini',
       config_parameter='odoo_ai.openai_model')

    # ── Claude ──────────────────────────────────────────────────
    odoo_ai_claude_api_key = fields.Char(
        string='Claude API Key',
        config_parameter='odoo_ai.claude_api_key',
    )
    odoo_ai_claude_model = fields.Selection([
        ('claude-sonnet-4-20250514', 'Claude Sonnet 4 (Best)'),
        ('claude-haiku-4-5-20251001', 'Claude Haiku 4.5 (Fast / Economy)'),
    ], string='Claude Model', default='claude-sonnet-4-20250514',
       config_parameter='odoo_ai.claude_model')

    # ── Gemini ──────────────────────────────────────────────────
    odoo_ai_gemini_api_key = fields.Char(
        string='Google Gemini API Key',
        config_parameter='odoo_ai.gemini_api_key',
    )
    odoo_ai_gemini_model = fields.Selection([
        ('gemini-1.5-flash', 'Gemini 1.5 Flash (Free Tier / Default)'),
        ('gemini-1.5-pro', 'Gemini 1.5 Pro (Best Quality)'),
        ('gemini-2.0-flash', 'Gemini 2.0 Flash (Latest)'),
    ], string='Gemini Model', default='gemini-1.5-flash',
       config_parameter='odoo_ai.gemini_model')

    # ── Groq (Free) ──────────────────────────────────────────
    odoo_ai_groq_api_key = fields.Char(
        string='Groq API Key',
        config_parameter='odoo_ai.groq_api_key',
    )
    odoo_ai_groq_model = fields.Selection([
        ('llama-3.1-8b-instant',    'Llama 3.1 8B — Fast & Free (Default)'),
        ('llama-3.3-70b-versatile', 'Llama 3.3 70B — Best Quality'),
        ('openai/gpt-oss-20b',      'GPT-OSS 20B'),
        ('openai/gpt-oss-120b',     'GPT-OSS 120B'),
    ], string='Groq Model', default='llama-3.1-8b-instant',
       config_parameter='odoo_ai.groq_model')

    # ── Self-heal retired / invalid stored model names ───────────
    @api.model
    def get_values(self):
        """If the stored Groq model is no longer a valid choice (e.g. a
        retired model), reset it so the Settings form can load and the
        controller stops sending a dead model name to Groq."""
        res = super().get_values()
        valid = {k for k, _label in self._fields['odoo_ai_groq_model'].selection}
        current = res.get('odoo_ai_groq_model')
        if current and current not in valid:
            default = 'llama-3.1-8b-instant'
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_ai.groq_model', default)
            res['odoo_ai_groq_model'] = default
        return res
