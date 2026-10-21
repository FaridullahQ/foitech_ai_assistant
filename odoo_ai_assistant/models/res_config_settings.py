# -*- coding: utf-8 -*-
import time

import requests

from odoo import _, api, fields, models

from .. import local_llm


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Provider Selection ──────────────────────────────────────
    odoo_ai_provider = fields.Selection([
        ('openai', 'OpenAI (ChatGPT)'),
        ('claude', 'Claude (Anthropic)'),
        ('gemini', 'Google Gemini'),
        ('groq',   'Groq — FREE (Llama3, no credit card)'),
        ('local',  'Local model — runs on your own server (Ollama)'),
    ], string='AI Provider', default='groq',
       config_parameter='odoo_ai.provider')

    # Model names for the cloud providers are free text: providers retire and
    # add models often, so a fixed list would go stale. Copy the current id
    # from the provider's documentation.

    # ── OpenAI ──────────────────────────────────────────────────
    odoo_ai_openai_api_key = fields.Char(
        string='OpenAI API Key',
        config_parameter='odoo_ai.openai_api_key',
    )
    odoo_ai_openai_model = fields.Char(
        string='OpenAI Model', default='gpt-5-mini',
        config_parameter='odoo_ai.openai_model',
        help='Model id from platform.openai.com, for example gpt-5-mini',
    )

    # ── Claude ──────────────────────────────────────────────────
    odoo_ai_claude_api_key = fields.Char(
        string='Claude API Key',
        config_parameter='odoo_ai.claude_api_key',
    )
    odoo_ai_claude_model = fields.Char(
        string='Claude Model', default='claude-sonnet-5-5',
        config_parameter='odoo_ai.claude_model',
        help='Model id from docs.anthropic.com, for example claude-sonnet-5-5',
    )

    # ── Gemini ──────────────────────────────────────────────────
    odoo_ai_gemini_api_key = fields.Char(
        string='Google Gemini API Key',
        config_parameter='odoo_ai.gemini_api_key',
    )
    odoo_ai_gemini_model = fields.Char(
        string='Gemini Model', default='gemini-flash-latest',
        config_parameter='odoo_ai.gemini_model',
        help='Model id from ai.google.dev, for example gemini-flash-latest',
    )

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

    # ── Local model (Ollama / self-hosted) ───────────────────────
    odoo_ai_local_type = fields.Selection([
        ('ollama', 'Ollama (native API)'),
        ('openai', 'OpenAI-compatible (LM Studio, vLLM, llama.cpp)'),
    ], string='Server Type', default='ollama',
       config_parameter='odoo_ai.local_type')
    odoo_ai_local_url = fields.Char(
        string='Server URL', default='http://localhost:11434',
        config_parameter='odoo_ai.local_url',
    )
    odoo_ai_local_model = fields.Char(
        string='Model Name',
        config_parameter='odoo_ai.local_model',
        help='Exactly as shown by "ollama list", for example qwen2.5:14b',
    )
    odoo_ai_local_api_key = fields.Char(
        string='API Key (optional)',
        config_parameter='odoo_ai.local_api_key',
    )
    odoo_ai_local_ctx = fields.Integer(
        string='Context Size (tokens)', default=16384,
        config_parameter='odoo_ai.local_ctx',
    )
    odoo_ai_local_timeout = fields.Integer(
        string='Timeout (seconds)', default=180,
        config_parameter='odoo_ai.local_timeout',
    )

    def action_odoo_ai_test_local(self):
        """Check the local model server: reachable, model installed, quick reply."""
        self.ensure_one()
        server_type = self.odoo_ai_local_type or 'ollama'
        model = (self.odoo_ai_local_model or '').strip()
        try:
            base = local_llm.normalize_local_url(self.odoo_ai_local_url, server_type)
            key = self.odoo_ai_local_api_key or ''
            installed = local_llm.fetch_local_models(base, server_type, key)
        except ValueError as e:
            return self._odoo_ai_notify(_('Local model'), str(e), 'danger')
        except requests.exceptions.RequestException as e:
            return self._odoo_ai_notify(
                _('Cannot reach the server'),
                _('Could not connect to %(url)s. Is Ollama running? (%(err)s)',
                  url=self.odoo_ai_local_url, err=str(e)[:200]),
                'danger')

        listing = ', '.join(installed[:12]) or _('none')
        if not model:
            return self._odoo_ai_notify(
                _('Server reachable'),
                _('Enter a model name. Installed models: %s', listing), 'warning')
        if model not in installed:
            return self._odoo_ai_notify(
                _('Model not found'),
                _('"%(model)s" is not installed. Installed models: %(list)s',
                  model=model, list=listing), 'danger')

        started = time.time()
        try:
            if server_type == 'ollama':
                resp = requests.post(
                    '%s/api/chat' % base, headers=local_llm.local_headers(key), timeout=120,
                    json={'model': model, 'stream': False,
                          'messages': [{'role': 'user', 'content': 'Reply with the word OK.'}],
                          'options': {'num_ctx': max(2048, self.odoo_ai_local_ctx or 16384),
                                      'num_predict': 16}})
            else:
                resp = requests.post(
                    '%s/chat/completions' % base, headers=local_llm.local_headers(key), timeout=120,
                    json={'model': model, 'stream': False, 'max_tokens': 16,
                          'messages': [{'role': 'user', 'content': 'Reply with the word OK.'}]})
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            return self._odoo_ai_notify(
                _('Model did not answer'), str(e)[:300], 'danger')
        secs = time.time() - started
        return self._odoo_ai_notify(
            _('Connection OK'),
            _('"%(model)s" answered in %(secs).1f s (the first call also loads the model into memory).',
              model=model, secs=secs),
            'success')

    @api.model
    def _odoo_ai_notify(self, title, message, kind):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': kind, 'sticky': kind != 'success'},
        }
