# -*- coding: utf-8 -*-
# Odoo AI Assistant — developed by Faridullah Qaderi (Faridullahqaderi54@gmail.com)
# Powered by FOITECH-Digital Solutions
import json
import logging
import re
import time
import requests
import base64
import io
from datetime import datetime, date

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

from .. import local_llm

_logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _json_serializer(obj):
    """Handle non-serializable objects from Odoo ORM."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'id'):
        return obj.id
    return str(obj)


def _safe_json(data):
    return json.dumps(data, default=_json_serializer)


def _post_json(provider_name, url, payload, headers):
    """POST to a provider; log the error body so HTTP failures are diagnosable."""
    resp = requests.post(url, json=payload, headers=headers, timeout=40)
    if not resp.ok:
        _logger.error(
            "AI provider %s returned HTTP %s: %s",
            provider_name, resp.status_code, resp.text[:500],
        )
    resp.raise_for_status()
    return resp


_STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'what', 'how', 'many',
    'much', 'show', 'list', 'all', 'give', 'get', 'are', 'was', 'were', 'have',
    'has', 'had', 'who', 'which', 'when', 'where', 'there', 'their', 'than',
    'then', 'into', 'over', 'per', 'each', 'any', 'can', 'you', 'please',
    'total', 'count', 'number', 'month', 'year', 'week', 'today', 'last',
    'new', 'top', 'name', 'names', 'records', 'record', 'data', 'status',
}


def _prompt_tokens(text):
    """Lower-cased keyword set (with naive singular forms) from free text."""
    out = set()
    for w in re.findall(r'[a-z0-9]+', (text or '').lower()):
        if len(w) < 3 or w in _STOPWORDS:
            continue
        out.add(w)
        if w.endswith('ies') and len(w) > 4:
            out.add(w[:-3] + 'y')
        elif w.endswith('es') and len(w) > 4:
            out.add(w[:-2])
        if w.endswith('s') and len(w) > 3:
            out.add(w[:-1])
    return out


def _rank_models(tokens, rows, limit=8):
    """Rank ir.model rows ({'model','name'}) by keyword overlap with the prompt."""
    scored = []
    for r in rows:
        tech = (r['model'] or '').lower()
        parts = set(re.findall(r'[a-z0-9]+', tech))
        parts |= set(re.findall(r'[a-z0-9]+', (r.get('name') or '').lower()))
        score = 0
        for t in tokens:
            if t in parts:
                score += 3
            elif len(t) >= 4 and any(p.startswith(t) for p in parts):
                score += 1
        if score:
            scored.append((-score, len(tech), tech, r['model']))
    scored.sort()
    return [x[3] for x in scored[:limit]]


# ─────────────────────────────────────────────
# AI Provider Adapters
# ─────────────────────────────────────────────

class AIProviderBase:
    # Prompt-size hints (smaller local models override these)
    schema_chars = 14000
    max_models = 8

    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model

    def chat(self, system_prompt, messages, json_mode=False):
        raise NotImplementedError


class OpenAIProvider(AIProviderBase):
    DEFAULT_MODEL = 'gpt-5-mini'

    @staticmethod
    def _is_reasoning_model(model):
        """GPT-5 and o-series models reject max_tokens / temperature."""
        return bool(re.match(r'^(gpt-5|o\d)', model or ''))

    def chat(self, system_prompt, messages, json_mode=False):
        url = 'https://api.openai.com/v1/chat/completions'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        model = self.model or self.DEFAULT_MODEL
        payload = {
            'model': model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
        }
        if self._is_reasoning_model(model):
            # Reasoning tokens count against the limit, so leave generous room
            payload['max_completion_tokens'] = 4096
            payload['reasoning_effort'] = 'low'
        else:
            payload['max_tokens'] = 1500
            payload['temperature'] = 0.2
        resp = _post_json('openai', url, payload, headers)
        return resp.json()['choices'][0]['message']['content']


class ClaudeProvider(AIProviderBase):
    DEFAULT_MODEL = 'claude-sonnet-5-5'

    def chat(self, system_prompt, messages, json_mode=False):
        url = 'https://api.anthropic.com/v1/messages'
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': self.model or self.DEFAULT_MODEL,
            'max_tokens': 1500,
            'system': system_prompt,
            'messages': messages,
        }
        resp = _post_json('claude', url, payload, headers)
        return resp.json()['content'][0]['text']


class GeminiProvider(AIProviderBase):
    DEFAULT_MODEL = 'gemini-flash-latest'

    def chat(self, system_prompt, messages, json_mode=False):
        model = self.model or self.DEFAULT_MODEL
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        headers = {'Content-Type': 'application/json', 'x-goog-api-key': self.api_key}

        # Gemini uses a different message format
        contents = []
        for msg in messages:
            role = 'user' if msg['role'] == 'user' else 'model'
            contents.append({'role': role, 'parts': [{'text': msg['content']}]})

        payload = {
            'system_instruction': {'parts': [{'text': system_prompt}]},
            'contents': contents,
            'generationConfig': {'maxOutputTokens': 1500, 'temperature': 0.2},
        }
        resp = _post_json('gemini', url, payload, headers)
        return resp.json()['candidates'][0]['content']['parts'][0]['text']


# (api_key tail, configured model) -> (resolved model, expiry timestamp)
_GROQ_MODEL_CACHE = {}


class GroqProvider(AIProviderBase):
    DEFAULT_MODEL = 'llama-3.3-70b-versatile'
    BASE_URL = 'https://api.groq.com/openai/v1'
    # Preferred order when the configured model is not available to this key
    PREFERRED_MODELS = [
        'llama-3.3-70b-versatile',
        'openai/gpt-oss-20b',
        'openai/gpt-oss-120b',
        'llama-3.1-8b-instant',
    ]
    # Models that cannot do plain chat completions
    _EXCLUDE = ('whisper', 'tts', 'guard', 'compound', 'orpheus', 'embed', 'safeguard')
    _MODEL_ERRORS = ('model_not_found', 'model_decommissioned')

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

    def _payload(self, model, system_prompt, messages):
        payload = {
            'model': model,
            'messages': [{'role': 'system', 'content': system_prompt}] + messages,
            'max_tokens': 1500,
            'temperature': 0.2,
        }
        if model.startswith('openai/gpt-oss'):
            # Reasoning models spend completion tokens on "thinking"; keep it short
            payload['reasoning_effort'] = 'low'
            payload['max_tokens'] = 4096
        return payload

    def _available_models(self):
        """Ask Groq which models this API key can actually use."""
        resp = requests.get(f'{self.BASE_URL}/models', headers=self._headers(), timeout=20)
        resp.raise_for_status()
        ids = [m['id'] for m in resp.json().get('data', []) if m.get('id')]
        return [i for i in ids if not any(x in i.lower() for x in self._EXCLUDE)]

    def _pick_fallback(self, tried):
        available = [m for m in self._available_models() if m != tried]
        _logger.info('Groq models available to this key: %s', available)
        for name in self.PREFERRED_MODELS:
            if name in available:
                return name
        return sorted(available)[0] if available else None

    def _error_code(self, resp):
        try:
            return (resp.json().get('error') or {}).get('code')
        except ValueError:
            return None

    def chat(self, system_prompt, messages, json_mode=False):
        url = f'{self.BASE_URL}/chat/completions'
        configured = self.model or self.DEFAULT_MODEL
        cache_key = (self.api_key[-8:], configured)
        hit = _GROQ_MODEL_CACHE.get(cache_key)
        model = hit[0] if hit and hit[1] > time.time() else configured

        _logger.info('Groq request: model=%s system_chars=%d message_chars=%d',
                     model, len(system_prompt),
                     sum(len(str(m.get('content', ''))) for m in messages))
        resp = requests.post(url, json=self._payload(model, system_prompt, messages),
                             headers=self._headers(), timeout=60)

        # Model is gone / not accessible -> pick one this key can use
        if not resp.ok and self._error_code(resp) in self._MODEL_ERRORS:
            _logger.warning('Groq model %s unavailable (%s); looking for a fallback.',
                            model, resp.text[:300])
            fallback = self._pick_fallback(model)
            if fallback:
                _logger.warning('Retrying Groq request with model %s', fallback)
                _GROQ_MODEL_CACHE[cache_key] = (fallback, time.time() + 3600)
                resp = requests.post(url, json=self._payload(fallback, system_prompt, messages),
                                     headers=self._headers(), timeout=60)

        if not resp.ok:
            _logger.error('AI provider groq returned HTTP %s: %s',
                          resp.status_code, resp.text[:500])
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message'].get('content') or ''
        # Some reasoning models inline their thoughts
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.S).strip()
        return content


class LocalProvider(AIProviderBase):
    """Self-hosted models. Server type 'ollama' uses Ollama's native /api/chat
    (which honours the context size per request); 'openai' targets any
    OpenAI-compatible server (LM Studio, vLLM, llama.cpp server, LocalAI)."""

    def __init__(self, api_key, model, base_url=None, server_type='ollama',
                 num_ctx=16384, timeout=180):
        super().__init__(api_key, model)
        self.server_type = server_type if server_type in local_llm.SERVER_TYPES else 'ollama'
        self.base_url = local_llm.normalize_local_url(
            base_url or 'http://localhost:11434', self.server_type)
        self.num_ctx = max(2048, int(num_ctx or 16384))
        self.timeout = max(10, int(timeout or 180))
        # ~3 characters per token; keep ~4000 tokens for rules, history and answer
        self.schema_chars = max(3000, min(14000, (self.num_ctx - 4000) * 3))
        self.max_models = 8 if self.num_ctx >= 12000 else 4

    def _post(self, url, payload):
        headers = local_llm.local_headers(self.api_key)
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        if not resp.ok and resp.status_code == 400 and 'response_format' in payload:
            # Some servers do not support JSON mode: retry once without it
            payload = {k: v for k, v in payload.items() if k != 'response_format'}
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        if not resp.ok:
            _logger.error('AI provider local returned HTTP %s: %s',
                          resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp

    def chat(self, system_prompt, messages, json_mode=False):
        msgs = [{'role': 'system', 'content': system_prompt}] + messages
        _logger.info('Local model request: server=%s model=%s ctx=%s system_chars=%d message_chars=%d',
                     self.server_type, self.model, self.num_ctx, len(system_prompt),
                     sum(len(str(m.get('content', ''))) for m in messages))
        if self.server_type == 'ollama':
            payload = {
                'model': self.model,
                'messages': msgs,
                'stream': False,
                'keep_alive': '30m',
                'options': {'num_ctx': self.num_ctx, 'num_predict': 2048, 'temperature': 0.1},
            }
            if json_mode:
                payload['format'] = 'json'
            data = self._post('%s/api/chat' % self.base_url, payload).json()
            content = (data.get('message') or {}).get('content') or ''
        else:
            payload = {
                'model': self.model,
                'messages': msgs,
                'stream': False,
                'temperature': 0.1,
                'max_tokens': 2048,
            }
            if json_mode:
                payload['response_format'] = {'type': 'json_object'}
            data = self._post('%s/chat/completions' % self.base_url, payload).json()
            content = data['choices'][0]['message'].get('content') or ''
        # Some reasoning models inline their thoughts
        return re.sub(r'<think>.*?</think>', '', content, flags=re.S).strip()


PROVIDER_MAP = {
    'openai': OpenAIProvider,
    'claude': ClaudeProvider,
    'gemini': GeminiProvider,
    'groq': GroqProvider,
    'local': LocalProvider,
}


# ─────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────

class AIAssistantController(http.Controller):

    # ── Routing ───────────────────────────────

    @http.route('/odoo_ai/query', type='json', auth='user', methods=['POST'], csrf=False)
    def ai_query(self, prompt, history=None):
        try:
            provider = self._get_provider()
            history = history or []

            # ── User access check ─────────────────────────────────────────
            allowed_models = request.env['odoo.ai.user.access'].sudo()                .get_allowed_models_for_user(request.env.uid)
            # None = unrestricted (admin or no rule defined)
            # set() = blocked entirely
            # {'sale.order',...} = restricted set

            if allowed_models is not None and len(allowed_models) == 0:
                return {
                    'success': False,
                    'answer': '🔒 You do not have access to any modules in the AI Assistant. '
                              'Please contact your administrator.',
                }

            # Build schema filtered to allowed models only
            schema = self._get_model_schema(
                allowed_models=allowed_models, prompt=prompt,
                history=history, provider=provider,
            )

            # Phase 1 — Plan the query
            plan = self._plan_query(provider, prompt, history, schema)

            # Keyword ranking may have missed the right models: let the AI pick
            # from the full model catalog and plan once more.
            if plan.get('type') == 'not_found':
                picked = self._select_models_with_llm(
                    provider, prompt, self._model_rows(allowed_models))
                tried = {m['model'] for m in schema}
                if picked and not set(picked) <= tried:
                    _logger.info('AI retry with models: %s', picked)
                    schema = self._get_model_schema(
                        allowed_models=allowed_models, prompt=prompt, history=history,
                        provider=provider, force_models=picked)
                    plan = self._plan_query(provider, prompt, history, schema)
            _logger.info("AI Query Plan: %s", plan)

            result_data = None
            chart_data = None
            export_data = None

            if plan.get('type') == 'odoo_query':
                result_data = self._execute_query(plan)

                # Build chart data if applicable
                if plan.get('chart') and result_data:
                    chart_data = self._build_chart_data(plan, result_data)

                # Build export payload
                if result_data:
                    export_data = self._build_export_data(result_data)

            # Phase 2 — Format the answer
            answer = self._format_answer(provider, prompt, plan, result_data)

            # Save to history model
            self._save_history(prompt, answer, plan.get('type', 'general'))

            return {
                'success': True,
                'answer': answer,
                'chart': chart_data,
                'export': export_data,
                'plan_type': plan.get('type'),
            }

        except requests.exceptions.ConnectionError:
            return {'success': False, 'answer': '⚠️ Could not reach the AI server. Check your internet connection and API key, or, for a local model, make sure Ollama is running and the server URL in Settings → AI Assistant is correct.'}
        except requests.exceptions.HTTPError as e:
            resp = e.response
            status = resp.status_code if resp is not None else 'unknown'
            body = (resp.text or '')[:500] if resp is not None else ''
            if status == 401:
                return {'success': False, 'answer': '⚠️ Invalid API key. Please update your AI provider API key in Settings → AI Assistant.'}
            if status == 429:
                return {'success': False, 'answer': '⚠️ API rate limit reached. Please wait a moment and try again.'}
            if status == 413 or 'context_length' in body or 'reduce the length' in body:
                return {'success': False, 'answer': '⚠️ The request was too large for the AI model. Please ask a more specific question, or choose a model with a larger limit in Settings.'}
            if status == 404 or 'model_not_found' in body:
                return {'success': False, 'answer': '⚠️ The selected AI model is not available for your API key. Please choose another model in Settings → AI Assistant.'}
            return {'success': False, 'answer': f'⚠️ AI provider returned an error (HTTP {status}). Please try again.'}
        except requests.exceptions.Timeout:
            return {'success': False, 'answer': '⚠️ The AI server took too long to answer. For a local model, increase the timeout in Settings, use a smaller model, or ask a simpler question.'}
        except AccessError:
            return {'success': False, 'answer': '⚠️ You do not have permission to access this data.'}
        except json.JSONDecodeError:
            return {'success': False, 'answer': '⚠️ The AI returned an unexpected response. Please rephrase your question.'}
        except Exception as e:
            _logger.exception("AI Assistant error for prompt: %s", prompt)
            return {'success': False, 'answer': f'⚠️ An unexpected error occurred: {str(e)}. Please try again or contact your administrator.'}

    @http.route('/odoo_ai/export', type='json', auth='user', methods=['POST'], csrf=False)
    def export_data(self, records, filename='ai_export'):
        """Generate a CSV from records and return base64 encoded content."""
        try:
            if not records:
                return {'success': False, 'message': 'No data to export.'}

            import csv
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)
            csv_content = output.getvalue()
            encoded = base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
            return {'success': True, 'content': encoded, 'filename': f'{filename}.csv'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @http.route('/odoo_ai/settings', type='json', auth='user', methods=['POST'], csrf=False)
    def get_settings(self):
        """Return current AI provider settings (no keys) for the frontend."""
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'provider': ICP.get_param('odoo_ai.provider', 'openai'),
            'openai_model': ICP.get_param('odoo_ai.openai_model', 'gpt-5-mini'),
            'claude_model': ICP.get_param('odoo_ai.claude_model', 'claude-sonnet-5-5'),
            'gemini_model': ICP.get_param('odoo_ai.gemini_model', 'gemini-flash-latest'),
            'groq_model': ICP.get_param('odoo_ai.groq_model', 'llama-3.1-8b-instant'),
            'local_model': ICP.get_param('odoo_ai.local_model', ''),
            'has_openai_key': bool(ICP.get_param('odoo_ai.openai_api_key')),
            'has_claude_key': bool(ICP.get_param('odoo_ai.claude_api_key')),
            'has_gemini_key': bool(ICP.get_param('odoo_ai.gemini_api_key')),
            'has_groq_key': bool(ICP.get_param('odoo_ai.groq_api_key')),
        }

    # ── Provider Setup ────────────────────────

    def _get_provider(self):
        ICP = request.env['ir.config_parameter'].sudo()
        provider_name = ICP.get_param('odoo_ai.provider', 'openai')
        key_map = {
            'openai': 'odoo_ai.openai_api_key',
            'claude': 'odoo_ai.claude_api_key',
            'gemini': 'odoo_ai.gemini_api_key',
            'groq':   'odoo_ai.groq_api_key',
        }
        model_map = {
            'openai': ICP.get_param('odoo_ai.openai_model', 'gpt-5-mini'),
            'claude': ICP.get_param('odoo_ai.claude_model', 'claude-sonnet-5-5'),
            'gemini': ICP.get_param('odoo_ai.gemini_model', 'gemini-flash-latest'),
            'groq':   ICP.get_param('odoo_ai.groq_model', 'llama-3.1-8b-instant'),
        }
        if provider_name == 'local':
            model = (ICP.get_param('odoo_ai.local_model') or '').strip()
            if not model:
                raise ValueError(
                    'No local model configured. In Settings -> AI Assistant, enter the '
                    'model name exactly as shown by "ollama list".'
                )

            def _int_param(key, default):
                try:
                    return int(ICP.get_param(key) or default)
                except (TypeError, ValueError):
                    return default

            return LocalProvider(
                api_key=ICP.get_param('odoo_ai.local_api_key', ''),
                model=model,
                base_url=ICP.get_param('odoo_ai.local_url', 'http://localhost:11434'),
                server_type=ICP.get_param('odoo_ai.local_type', 'ollama'),
                num_ctx=_int_param('odoo_ai.local_ctx', 16384),
                timeout=_int_param('odoo_ai.local_timeout', 180),
            )
        api_key = ICP.get_param(key_map.get(provider_name, 'odoo_ai.openai_api_key'), '')
        if not api_key:
            raise ValueError(
                f'No API key configured for provider "{provider_name}". '
                'Please set it in Settings → AI Assistant.'
            )
        cls = PROVIDER_MAP.get(provider_name, OpenAIProvider)
        return cls(api_key=api_key, model=model_map.get(provider_name))

    # ── Schema Builder ────────────────────────

    # Technical models never useful for business questions
    _SKIP_MODEL_PREFIXES = (
        'ir.', 'base.', 'bus.', 'web.', 'auth.', 'report.', 'res.config',
        'mail.', 'wizard.', 'base_import.', 'iap.', 'format.address',
        'odoo.ai.', 'resource.', 'privacy.', 'sms.', 'digest.',
    )
    _SKIP_FIELDS = {'create_uid', 'write_uid', 'write_date', 'display_name', 'id'}
    _SKIP_FIELD_PREFIXES = ('message_', 'activity_', 'website_message', 'access_', 'my_activity')
    _COMMON_MODELS = (
        'res.partner', 'sale.order', 'purchase.order', 'account.move',
        'product.product', 'product.template', 'hr.employee', 'stock.picking',
        'crm.lead', 'project.task',
    )
    MAX_SCHEMA_CHARS = 14000

    def _model_rows(self, allowed_models=None):
        """All candidate business models as [{'model', 'name'}, ...]."""
        domain = [('transient', '=', False)]
        if allowed_models is not None:
            domain.append(('model', 'in', list(allowed_models)))
        rows = request.env['ir.model'].sudo().search_read(
            domain, ['model', 'name'], order='model asc')
        if allowed_models is None:
            rows = [r for r in rows if not r['model'].startswith(self._SKIP_MODEL_PREFIXES)]
        return rows

    def _get_model_schema(self, allowed_models=None, prompt='', history=None,
                          provider=None, force_models=None):
        """
        Build a COMPACT schema containing only the models relevant to the
        question, so the planner prompt stays small enough for any provider.
        allowed_models: None = all, set = restrict to those model names.
        """
        env = request.env
        rows = self._model_rows(allowed_models)
        if not rows:
            return []

        # Also look at the last couple of user turns so follow-ups keep context
        text = prompt or ''
        for h in (history or [])[-4:]:
            if isinstance(h, dict) and h.get('role') == 'user':
                text += ' ' + str(h.get('content', ''))

        valid_names = {r['model'] for r in rows}
        max_models = getattr(provider, 'max_models', 8)
        chosen = [m for m in (force_models or []) if m in valid_names]
        if not chosen:
            chosen = _rank_models(_prompt_tokens(text), rows, limit=max_models)
        if not chosen and provider is not None:
            chosen = self._select_models_with_llm(provider, prompt, rows)
        if not chosen:
            names = {r['model'] for r in rows}
            chosen = [m for m in self._COMMON_MODELS if m in names][:max_models] or \
                     [r['model'] for r in rows[:max_models]]
        _logger.info('AI schema models selected: %s', chosen)

        by_name = {r['model']: r for r in rows}
        model_recs = env['ir.model'].sudo().search([('model', 'in', chosen)])
        id_to_model = {m.id: m.model for m in model_recs}
        field_rows = env['ir.model.fields'].sudo().search_read(
            [
                ('model_id', 'in', list(id_to_model)),
                ('store', '=', True),
                ('ttype', 'in', [
                    'char', 'text', 'selection', 'many2one', 'integer', 'float',
                    'boolean', 'date', 'datetime', 'monetary',
                ]),
            ],
            ['model_id', 'name', 'ttype', 'field_description', 'selection'],
        )
        per_model = {}
        for f in field_rows:
            name = f['name']
            if name in self._SKIP_FIELDS or name.startswith(self._SKIP_FIELD_PREFIXES):
                continue
            per_model.setdefault(id_to_model.get(f['model_id'][0]), []).append(f)

        def priority(f):
            n = f['name']
            first = n in ('name', 'state', 'partner_id', 'create_date') or \
                n.startswith(('date', 'amount', 'total'))
            return (0 if first else 1, n)

        schema = []
        for limit in (40, 25, 15, 8):
            schema = []
            for model in chosen:
                fl = sorted(per_model.get(model, []), key=priority)[:limit]
                strings = []
                for f in fl:
                    item = f"{f['name']}:{f['ttype']}:{f['field_description']}"
                    if f['ttype'] == 'selection' and f.get('selection'):
                        item += ' ' + str(f['selection'])[:200]
                    strings.append(item)
                schema.append({
                    'model': model,
                    'name': by_name.get(model, {}).get('name', model),
                    'fields': strings,
                })
            if len(json.dumps(schema, default=_json_serializer)) <= getattr(
                    provider, 'schema_chars', self.MAX_SCHEMA_CHARS):
                break
        return schema

    def _select_models_with_llm(self, provider, prompt, rows):
        """Fallback when keywords match nothing (e.g. non-English questions,
        or models whose names don't contain the user's words): show the model
        catalog (technical names only) and let the AI pick."""
        try:
            catalog = '\n'.join(r['model'] for r in rows)[:12000]
            raw = provider.chat(
                'You select Odoo models relevant to a question. Return ONLY a JSON '
                'array (max 6 items) of technical model names taken from the catalog. '
                'No other text.',
                [{'role': 'user',
                  'content': 'Catalog (technical model names):\n%s\n\nQuestion: %s' % (catalog, prompt)}],
            )
            m = re.search(r'\[.*?\]', raw, re.S)
            names = json.loads(m.group(0)) if m else []
            valid = {r['model'] for r in rows}
            return [n for n in names if isinstance(n, str) and n in valid][:getattr(provider, 'max_models', 6)]
        except Exception as e:
            _logger.warning('AI model pre-selection failed: %s', e)
            return []

    # ── Query Planner ─────────────────────────

    def _plan_query(self, provider, prompt, history, schema):
        schema_text = json.dumps(schema, separators=(',', ':'), default=_json_serializer)
        today = date.today().isoformat()

        system_prompt = f"""
You are an Odoo 17 data query planner. Today's date is {today}.

Your job: analyze the user's natural-language question and return a SINGLE valid JSON object (no markdown fences, no extra text).

Available Odoo models and fields (each field is "name:type:Label"):
{schema_text}

─── OUTPUT FORMATS ───────────────────────────────────────

1. For data queries:
{{
  "type": "odoo_query",
  "model": "sale.order",
  "method": "search_count" | "search_read" | "read_group",
  "domain": [["state", "=", "sale"]],
  "fields": ["name", "partner_id", "amount_total", "state"],
  "groupby": ["state"],
  "limit": 20,
  "order": "date_order desc",
  "chart": {{
    "type": "bar" | "pie" | "line",
    "label_field": "state",
    "value_field": "amount_total"
  }},
  "description": "Human readable description of this query"
}}

2. For general / non-data questions:
{{
  "type": "general",
  "answer": "Your direct answer here"
}}

3. When the question cannot be answered:
{{
  "type": "not_found",
  "reason": "Explain clearly why this cannot be answered"
}}

─── RULES ────────────────────────────────────────────────
- Use search_count for "how many" questions (no fields needed)
- Use search_read for listing records (include fields array, max limit 50)
- Use read_group for grouped/aggregated data (include groupby + fields with aggregate functions like sum)
- For read_group fields that aggregate, use syntax: ["state", "amount_total:sum"]
- domain uses Odoo domain syntax: [["field", "operator", "value"]]
- Date operators: use "date_order", "date", "create_date" etc.
- For "this month": [["create_date", ">=", "{date.today().replace(day=1).isoformat()}"]]
- For "expired": look for state="expired" or date fields < today
- Only use models and fields that exist in the schema above
- NEVER suggest write/create/unlink/delete operations
- If a model is not in the schema, return type "not_found"
- Include chart only when groupby is used or results are naturally comparable
- Keep limit to 20 by default, max 50
"""
        messages = history[-6:] + [{'role': 'user', 'content': prompt}]
        raw = provider.chat(system_prompt, messages, json_mode=True)
        try:
            return self._parse_plan(raw)
        except json.JSONDecodeError:
            _logger.warning('AI plan was not valid JSON, retrying once: %s', (raw or '')[:300])
            retry = messages + [
                {'role': 'assistant', 'content': (raw or '')[:800]},
                {'role': 'user', 'content': 'Your last reply was not valid JSON. Reply again '
                                            'with ONLY one valid JSON object and no other text.'},
            ]
            return self._parse_plan(provider.chat(system_prompt, retry, json_mode=True))

    @staticmethod
    def _parse_plan(raw):
        """Parse the plan, tolerating code fences and text around the JSON."""
        clean = (raw or '').strip()
        clean = re.sub(r'^```(?:json)?', '', clean).strip()
        clean = re.sub(r'```$', '', clean).strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', clean, re.S)
            if m:
                return json.loads(m.group(0))
            raise

    # ── Query Executor ────────────────────────

    # ── Read-only: ONLY these ORM methods are ever permitted ──────────────
    ALLOWED_METHODS = {'search_count', 'search_read', 'read_group'}
    MAX_LIMIT = 50

    def _execute_query(self, plan):
        model_name = plan.get('model', '')
        method = plan.get('method', 'search_count')
        domain = plan.get('domain', [])
        fields = plan.get('fields', [])
        groupby = plan.get('groupby', [])
        limit = min(int(plan.get('limit', 20)), self.MAX_LIMIT)
        order = plan.get('order', False)

        # ── SECURITY 1: Read-only enforcement ─────────────────────────────
        # Absolutely block any write/create/unlink regardless of how the AI
        # or a malicious prompt tries to call them.
        if method not in self.ALLOWED_METHODS:
            _logger.warning(
                'AI Assistant blocked forbidden method %s on model %s by user %s',
                method, model_name, request.env.uid
            )
            raise ValueError(
                f'Operation {method} is not allowed. '
                'The AI Assistant is read-only and cannot modify any data.'
            )

        # ── SECURITY 2: User module access check ──────────────────────────
        allowed_models = request.env['odoo.ai.user.access'].sudo()            .get_allowed_models_for_user(request.env.uid)
        if allowed_models is not None and model_name not in allowed_models:
            _logger.warning(
                'AI Assistant blocked access to model %s for user %s (not in allowed list)',
                model_name, request.env.uid
            )
            raise AccessError(
                f'You do not have permission to query {model_name}. '
                'Ask your administrator to grant access to this module.'
            )

        env = request.env
        # NOTE: do not use `not env.get(name)` - an empty recordset is falsy,
        # which made every existing model look "missing".
        if model_name not in env:
            raise ValueError(f'Model "{model_name}" is not installed in this database.')

        obj = env[model_name]

        try:
            if method == 'search_count':
                count = obj.search_count(domain)
                return {'count': count, 'model': model_name}

            elif method == 'search_read':
                kwargs = {'domain': domain, 'fields': fields, 'limit': limit}
                if order:
                    kwargs['order'] = order
                records = obj.search_read(**kwargs)
                # Flatten many2one tuples → readable names
                for rec in records:
                    for k, v in rec.items():
                        if isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], int):
                            rec[k] = v[1]
                return {'records': records, 'total': len(records), 'model': model_name}

            elif method == 'read_group':
                # Separate aggregate fields from groupby fields for read_group
                result = obj.read_group(domain, fields=fields, groupby=groupby, lazy=False)
                # Clean up result
                clean_result = []
                for r in result:
                    clean_r = {}
                    for k, v in r.items():
                        if k.startswith('__'):
                            continue
                        if isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], int):
                            clean_r[k] = v[1]
                        else:
                            clean_r[k] = v
                    clean_result.append(clean_r)
                return {'groups': clean_result, 'model': model_name}

        except AccessError:
            raise AccessError(f'You do not have read access to "{model_name}".')
        except Exception as e:
            _logger.warning("Query execution error: %s | Plan: %s", e, plan)
            raise ValueError(f'Query failed on model "{model_name}": {str(e)}')

    # ── Chart Builder ─────────────────────────

    def _build_chart_data(self, plan, result_data):
        chart_cfg = plan.get('chart', {})
        chart_type = chart_cfg.get('type', 'bar')
        label_field = chart_cfg.get('label_field')
        value_field = chart_cfg.get('value_field')

        rows = result_data.get('groups') or result_data.get('records') or []
        if not rows or not label_field:
            return None

        # Normalize value_field key (read_group returns "amount_total:sum" as "amount_total")
        norm_value = value_field.split(':')[0] if value_field else None

        labels, values = [], []
        for row in rows:
            lbl = row.get(label_field, 'Unknown')
            if isinstance(lbl, bool):
                lbl = 'Yes' if lbl else 'No'
            labels.append(str(lbl))
            if norm_value:
                val = row.get(norm_value, row.get(value_field, 0))
                values.append(round(float(val or 0), 2))
            else:
                values.append(row.get('__count', 1))

        return {'type': chart_type, 'labels': labels, 'values': values,
                'label': value_field or 'Count'}

    # ── Export Builder ────────────────────────

    def _build_export_data(self, result_data):
        records = (result_data.get('records')
                   or result_data.get('groups')
                   or [])
        if result_data.get('count') is not None:
            return None  # Nothing to export for count queries
        if not records:
            return None
        return records

    # ── Answer Formatter ──────────────────────

    def _format_answer(self, provider, prompt, plan, result_data):
        if plan.get('type') == 'general':
            return plan.get('answer', 'I could not find an answer.')

        if plan.get('type') == 'not_found':
            reason = plan.get('reason', 'The requested data could not be found.')
            return f'ℹ️ {reason}'

        if plan.get('type') != 'odoo_query' or result_data is None:
            return '⚠️ No data was retrieved.'

        data_summary = _safe_json(result_data)[:8000]

        system_prompt = """
You are a helpful Odoo business assistant. Format the query result into a 
clear, friendly, and concise natural language answer.

Guidelines:
- Use plain language, no technical jargon
- Use numbers clearly (e.g. "23 customers")
- If listing records, use a brief bulleted format (max 10 items shown)
- If there are more records than shown, mention the total
- If count is 0 or empty, say clearly "No records found" with a helpful note
- Highlight important insights if obvious
- Do NOT show JSON or field names — translate to human-readable labels
- Keep the answer under 200 words
- Format with simple markdown ONLY: **bold**, "- " bullet lines, numbered lines, and
  markdown tables when comparing several fields. NEVER output HTML tags such as <br>.
"""
        content = f'User asked: {prompt}\n\nData retrieved: {data_summary}\n\nProvide a clear, concise answer.'
        try:
            return provider.chat(system_prompt, [{'role': 'user', 'content': content}])
        except Exception as e:
            _logger.warning("Format answer failed: %s", e)
            return _safe_json(result_data)

    # ── History ───────────────────────────────

    def _save_history(self, prompt, answer, query_type):
        try:
            request.env['odoo.ai.chat.history'].sudo().create({
                'user_id': request.env.user.id,
                'prompt': prompt,
                'answer': answer,
                'query_type': query_type,
            })
        except Exception:
            pass  # History is non-critical
