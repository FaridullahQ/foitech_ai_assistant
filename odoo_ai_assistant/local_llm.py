# -*- coding: utf-8 -*-
# Odoo AI Assistant — developed by Faridullah Qaderi (Faridullahqaderi54@gmail.com)
# Powered by FOITECH-Digital Solutions
"""Helpers for self-hosted models (Ollama, LM Studio, vLLM, llama.cpp server)."""
import re

import requests

SERVER_TYPES = ('ollama', 'openai')


def normalize_local_url(url, server_type='ollama'):
    """Return a clean base URL for the configured server type.

    ollama -> http://host:11434          (native API: /api/chat, /api/tags)
    openai -> http://host:1234/v1        (OpenAI-compatible: /chat/completions, /models)
    """
    url = (url or '').strip().rstrip('/')
    if not re.match(r'^https?://[^/\s]+', url, re.I):
        raise ValueError('The local model server URL must start with http:// or https://')
    low = url.lower()
    if server_type == 'ollama':
        for suffix in ('/v1', '/api'):
            if low.endswith(suffix):
                url = url[:-len(suffix)]
                low = url.lower()
    elif not low.endswith('/v1'):
        url += '/v1'
    return url


def local_headers(api_key=''):
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer %s' % api_key
    return headers


def fetch_local_models(base_url, server_type='ollama', api_key='', timeout=10):
    """List the model names installed on the server."""
    headers = local_headers(api_key)
    if server_type == 'ollama':
        resp = requests.get('%s/api/tags' % base_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return [m.get('name') or m.get('model') for m in resp.json().get('models', [])]
    resp = requests.get('%s/models' % base_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return [m.get('id') for m in resp.json().get('data', []) if m.get('id')]
