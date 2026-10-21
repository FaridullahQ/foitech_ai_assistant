# AI Assistant for Odoo

Chat with your Odoo data in plain language. A floating AI assistant turns your
questions into safe, **read-only** queries and answers with text, tables, charts
and CSV export. Use a cloud AI provider, or run an open-source model on your own
machine so your data never leaves your network.

- **Odoo version:** 17.0
- **License:** LGPL-3
- **Developer:** Faridullah Qaderi, FOITECH-Digital Solutions
- **Contact:** Faridullahqaderi54@gmail.com | WhatsApp (+93) 788 70 74 79 | https://www.foitech.com

## Features

- Natural-language questions across any installed module
- Read-only: only `search_count`, `search_read`, `read_group`, executed as the logged-in user
- Providers: OpenAI, Claude, Gemini, Groq, local models (Ollama, LM Studio, vLLM, llama.cpp)
- Bar, line and pie charts (Chart.js bundled, works offline), CSV export
- Conversation history and per-user module access control

## Installation

1. Copy `foitech_ai_assistant` into your addons path.
2. `pip install requests` (usually already present).
3. Restart Odoo, then **Apps > Update Apps List**, search **AI Assistant for Odoo**, **Install**.
4. **Settings > AI Assistant Settings**: choose a provider, fill in its fields, **Save**.
5. Click the round button at the bottom-right and ask a question.

Upgrade: `odoo-bin -u foitech_ai_assistant -d YOUR_DB`, then hard-refresh the browser (Ctrl+F5).

## Local model with Ollama

1. Install Ollama from https://ollama.com/download
2. Pull a model, for example `ollama pull qwen2.5:14b` (14B and above recommended).
   Rough memory: 7-8B about 6 GB, 14B about 10-12 GB, 30B-class about 20 GB or more.
3. Check: `ollama list` and `curl http://localhost:11434/api/tags`
   (PowerShell: `curl.exe` or `Invoke-RestMethod`).
4. In Odoo choose **Local model** and set:

   | Field | Value |
   |---|---|
   | Server Type | Ollama (native API) |
   | Server URL | `http://localhost:11434` (or `http://SERVER-IP:11434`) |
   | Model Name | exactly as in `ollama list`, e.g. `qwen2.5:14b` |
   | API Key | empty (only for a reverse proxy that needs one) |
   | Context Size | `16384` (`8192` if memory is tight) |
   | Timeout | `180` seconds (`300`+ on CPU only) |

5. Click **Test connection**, then **Save**.

**Ollama on another server:** set `OLLAMA_HOST=0.0.0.0:11434` there, open port 11434 only
to the Odoo server, and never expose it to the internet. Use a reverse proxy with an API
key and HTTPS for shared use.

**LM Studio / vLLM / llama.cpp:** choose Server Type *OpenAI-compatible* and enter the
address including `/v1` (for example `http://localhost:1234/v1`). The context size is set on
the server in this mode.

### Troubleshooting

| You see | Try |
|---|---|
| Could not reach the AI server | Is Ollama running? Check URL and firewall; test with curl from the Odoo server |
| Model not found | Name must match `ollama list` exactly, including the tag; run `ollama pull` |
| Very slow answers | Use a GPU, a smaller model or a lower context size |
| Took too long to answer | Raise the Timeout; with workers also raise `limit_time_real` in `odoo.conf` |
| Wrong or empty answers | Use a 14B+ model; small models struggle with structured output |

## Cloud providers

| Provider | Get a key | Key looks like | Model field |
|---|---|---|---|
| Groq | https://console.groq.com > API Keys | `gsk_...` | dropdown (auto-fallback if unavailable) |
| OpenAI | https://platform.openai.com > API keys (add credits) | `sk-...` | free text, e.g. `gpt-5-mini` |
| Claude | https://console.anthropic.com > API Keys (add credits) | `sk-ant-...` | free text, e.g. `claude-sonnet-5-5` |
| Gemini | https://aistudio.google.com/apikey | `AIza...` | free text, e.g. `gemini-flash-latest` |

Providers retire and add models often. If you see "model not available", copy a current
model id from the provider's documentation.

## Access control

**AI Assistant > User Module Access** > New. Administrators and AI Super Users are
unrestricted; users without a rule are open by default; a rule with modules restricts to
those modules; a rule with no modules blocks the user.

## Privacy

With a cloud provider the AI receives the question, the names and labels of the few
relevant models and fields, and up to 50 result rows used to write the answer. With a
local model nothing leaves your network. API keys are stored in Odoo system parameters
(administrators only).
