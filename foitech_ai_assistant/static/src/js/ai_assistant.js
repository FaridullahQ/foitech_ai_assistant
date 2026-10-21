/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// ─── Safe markdown-lite renderer ────────────────────────────────────────────
// Escapes ALL html first (answers may contain database text), then converts
// a small markdown subset (bold, headings, bullet/numbered lists, tables).
function escapeHtml(s) {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function inlineMd(s) {
    return s
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderMarkdownLite(text) {
    // The model sometimes emits <br> tags itself: treat them as line breaks
    const src = String(text || "").replace(/\r\n/g, "\n").replace(/<br\s*\/?>/gi, "\n");
    const lines = escapeHtml(src).split("\n");

    const isTableRow = (l) => /^\s*\|.*\|\s*$/.test(l);
    const isSeparator = (l) => /^\s*\|?[\s:|-]+\|?\s*$/.test(l) && l.includes("-");
    const bulletRe = /^\s*[-*\u2022]\s+(.*)$/;
    const numberRe = /^\s*\d+[.)]\s+(.*)$/;
    const headingRe = /^\s*#{1,6}\s+(.*)$/;
    const isSpecial = (l) =>
        isTableRow(l) || bulletRe.test(l) || numberRe.test(l) || headingRe.test(l);

    const out = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) { i++; continue; }

        if (isTableRow(line)) {
            const rows = [];
            while (i < lines.length && isTableRow(lines[i])) { rows.push(lines[i]); i++; }
            const cells = (r) =>
                r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inlineMd(c.trim()));
            const body = rows.filter((r) => !isSeparator(r)).map(cells);
            if (body.length) {
                const head = body[0].map((c) => `<th>${c}</th>`).join("");
                const rest = body.slice(1)
                    .map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`)
                    .join("");
                out.push(`<div class="ai-md-table-wrap"><table class="ai-md-table"><thead><tr>${head}</tr></thead><tbody>${rest}</tbody></table></div>`);
            }
            continue;
        }

        if (headingRe.test(line)) {
            out.push(`<div class="ai-md-heading">${inlineMd(line.match(headingRe)[1].trim())}</div>`);
            i++;
            continue;
        }

        if (bulletRe.test(line) || numberRe.test(line)) {
            const ordered = numberRe.test(line) && !bulletRe.test(line);
            const re = ordered ? numberRe : bulletRe;
            const items = [];
            while (i < lines.length && re.test(lines[i])) {
                items.push(`<li>${inlineMd(lines[i].match(re)[1].trim())}</li>`);
                i++;
            }
            out.push(`<${ordered ? "ol" : "ul"} class="ai-md-list">${items.join("")}</${ordered ? "ol" : "ul"}>`);
            continue;
        }

        const para = [];
        while (i < lines.length && lines[i].trim() && !isSpecial(lines[i])) {
            para.push(inlineMd(lines[i].trim()));
            i++;
        }
        out.push(`<p class="ai-md-p">${para.join("<br/>")}</p>`);
    }
    return out.join("");
}

// ─── Chart.js lazy loader ───────────────────────────────────────────────────
let chartJsLoaded = false;
async function loadChartJs() {
    if (chartJsLoaded || window.Chart) { chartJsLoaded = true; return; }
    await new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = '/foitech_ai_assistant/static/lib/chartjs/chart.umd.js';
        s.onload = resolve; s.onerror = reject;
        document.head.appendChild(s);
    });
    chartJsLoaded = true;
}

// ─── Module information (shown in the About panel) ──────────────────────────
const MODULE_INFO = {
    name: "Odoo AI Assistant",
    version: "17.0.1.0.4",
    developer: "Faridullah Qaderi",
    email: "Faridullahqaderi54@gmail.com",
    phone: "(+93) 788 70 74 79",
    phoneRaw: "+93788707479",
    whatsapp: "https://wa.me/93788707479",
    company: "FOITECH-Digital Solutions",
};

// ─── Suggestion pills ───────────────────────────────────────────────────────
const SUGGESTIONS = [
    "How many customers do we have?",
    "How many confirmed sale orders this month?",
    "How many contracts are expired?",
    "How many products are out of stock?",
    "Count employees by department",
    "How many draft invoices exist?",
    "List overdue purchase orders",
    "How many leads are in each CRM stage?",
];

// ─── Main Component ─────────────────────────────────────────────────────────
export class AIAssistant extends Component {
    static template = "foitech_ai_assistant.AIAssistant";

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");

        // Handlers used inside arrow functions in the template lose `this`
        // unless they are bound explicitly.
        this.selectSuggestion = this.selectSuggestion.bind(this);
        this.exportCSV = this.exportCSV.bind(this);

        this.state = useState({
            open: false,
            loading: false,
            prompt: "",
            messages: [],         // [{role, text, chart, export}]
            provider: "openai",
            providerLabel: "OpenAI",
            minimized: false,
            showSuggestions: true,
            showAbout: false,
        });

        this.chartInstances = {};
        this.inputRef = useRef("promptInput");
        this.messagesRef = useRef("messagesContainer");
        this.chartRefs = {};

        // Load current provider label on mount
        onMounted(() => this._loadSettings());
        onWillUnmount(() => this._destroyAllCharts());
    }

    // ── Settings ──────────────────────────────────────────────────────────

    async _loadSettings() {
        try {
            const settings = await this.rpc("/odoo_ai/settings", {});
            const labels = { openai: "OpenAI", claude: "Claude", gemini: "Gemini", groq: "Groq", local: "Local model" };
            this.state.provider = settings.provider;
            this.state.providerLabel = labels[settings.provider] || settings.provider;
        } catch (e) {
            // non-critical
        }
    }

    // ── Open / Close ──────────────────────────────────────────────────────

    toggleOpen() {
        this.state.open = !this.state.open;
        this.state.minimized = false;
        this.state.showAbout = false;
        if (this.state.open && this.state.messages.length === 0) {
            this.state.showSuggestions = true;
        }
    }

    toggleAbout() { this.state.showAbout = !this.state.showAbout; }

    minimize() { this.state.minimized = true; }
    restore()  { this.state.minimized = false; }

    clearChat() {
        this._destroyAllCharts();
        this.state.messages = [];
        this.state.showSuggestions = true;
        this.conversationHistory = [];
    }

    // ── Messaging ─────────────────────────────────────────────────────────

    conversationHistory = [];   // Kept in sync for multi-turn context

    handleKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    selectSuggestion(text) {
        this.state.prompt = text;
        this.state.showSuggestions = false;
        this.sendMessage();
    }

    async sendMessage() {
        const prompt = this.state.prompt.trim();
        if (!prompt || this.state.loading) return;

        this.state.prompt = "";
        this.state.showSuggestions = false;
        this.state.loading = true;

        // Push user message
        this.state.messages.push({ role: "user", text: prompt });
        this._scrollBottom();

        // Add to history for context
        this.conversationHistory.push({ role: "user", content: prompt });

        try {
            const result = await this.rpc("/odoo_ai/query", {
                prompt,
                history: this.conversationHistory.slice(-10),   // last 10 turns
            });

            const assistantMsg = {
                role: "assistant",
                text: result.answer || "No response.",
                chart: result.chart || null,
                export: result.export || null,
                success: result.success !== false,
            };
            this.state.messages.push(assistantMsg);
            this.conversationHistory.push({ role: "assistant", content: result.answer });

            // Render chart after DOM update
            if (result.chart) {
                await this._nextTick();
                this._renderChart(this.state.messages.length - 1, result.chart);
            }
        } catch (e) {
            this.state.messages.push({
                role: "assistant",
                text: "⚠️ Could not reach the server. Please refresh and try again.",
                success: false,
            });
        } finally {
            this.state.loading = false;
            this._scrollBottom();
        }
    }

    // ── Chart Rendering ───────────────────────────────────────────────────

    async _renderChart(msgIndex, chartData) {
        await loadChartJs();
        const canvasId = `ai-chart-${msgIndex}`;
        const canvas = document.getElementById(canvasId);
        if (!canvas || !window.Chart) return;

        // Destroy previous instance if exists
        if (this.chartInstances[canvasId]) {
            this.chartInstances[canvasId].destroy();
        }

        // First colour follows the active Odoo theme (Bootstrap primary)
        let primary = "";
        try {
            primary = getComputedStyle(document.documentElement)
                .getPropertyValue("--bs-primary").trim();
        } catch (e) { /* ignore */ }
        if (!/^#[0-9a-f]{6}$/i.test(primary)) { primary = '#22d3ee'; }
        const colors = [
            primary,'#22d3ee','#f59e0b','#10b981','#f43f5e',
            '#8b5cf6','#14b8a6','#fb923c','#84cc16','#e879f9',
        ];
        const bgColors = colors.map(c => c + 'cc');

        const config = {
            type: chartData.type || 'bar',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: chartData.label || 'Value',
                    data: chartData.values,
                    backgroundColor: chartData.type === 'pie' ? bgColors : bgColors[0],
                    borderColor: chartData.type === 'pie' ? colors : colors[0],
                    borderWidth: 1.5,
                    borderRadius: chartData.type === 'bar' ? 6 : 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: chartData.type === 'pie',
                        labels: { color: 'rgba(241,245,255,0.85)', font: { size: 11 } },
                    },
                    tooltip: { callbacks: { label: ctx => ` ${ctx.formattedValue}` } },
                },
                scales: chartData.type === 'pie' ? {} : {
                    x: { ticks: { color: 'rgba(226,232,240,0.7)' }, grid: { color: 'rgba(255,255,255,0.08)' } },
                    y: { ticks: { color: 'rgba(226,232,240,0.7)' }, grid: { color: 'rgba(255,255,255,0.08)' } },
                },
            },
        };

        this.chartInstances[canvasId] = new window.Chart(canvas, config);
    }

    _destroyAllCharts() {
        Object.values(this.chartInstances).forEach(c => { try { c.destroy(); } catch(e){} });
        this.chartInstances = {};
    }

    // ── Export ────────────────────────────────────────────────────────────

    async exportCSV(msgIndex) {
        const msg = this.state.messages[msgIndex];
        if (!msg || !msg.export) return;
        try {
            const result = await this.rpc("/odoo_ai/export", {
                records: msg.export,
                filename: `ai_export_${Date.now()}`,
            });
            if (result.success) {
                // Trigger browser download
                const a = document.createElement('a');
                a.href = `data:text/csv;base64,${result.content}`;
                a.download = result.filename;
                a.click();
            } else {
                this.notification.add(result.message || "Export failed.", { type: "danger" });
            }
        } catch(e) {
            this.notification.add("Export error: " + e.message, { type: "danger" });
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    _scrollBottom() {
        setTimeout(() => {
            const el = this.messagesRef.el;
            if (el) el.scrollTop = el.scrollHeight;
        }, 50);
    }

    _nextTick() {
        return new Promise(r => setTimeout(r, 80));
    }

    getProviderBadgeClass() {
        const map = { openai: 'ai-badge-openai', claude: 'ai-badge-claude', gemini: 'ai-badge-gemini' };
        return map[this.state.provider] || 'ai-badge-openai';
    }

    formatText(text) {
        // Safe: renderMarkdownLite escapes all HTML before adding its own tags
        return markup(renderMarkdownLite(text));
    }

    get suggestions() { return SUGGESTIONS; }
    get about() { return MODULE_INFO; }
}

AIAssistant.template = "foitech_ai_assistant.AIAssistant";

// Register as a systray service / action
registry.category("systray").add("foitech_ai_assistant", {
    Component: AIAssistant,
    sequence: 1,
});
