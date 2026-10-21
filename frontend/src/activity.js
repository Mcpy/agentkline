// ============================================================
// 动态：给用户看的人话事件流（v0.6.0）
// 原始 WS 日志仍在 log.js（工作坞「调试」页），这里只收发生了什么
// ============================================================
import { t } from './i18n.js';
import { state } from './state.js';
import { formatClock } from './format.js';

const MAX = 100;
const items = [];
let _seq = 0;

function _fmtPct(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return '';
    return (n >= 0 ? '+' : '') + (n * 100).toFixed(2) + '%';
}

export function addActivity(kind, text, opts = {}) {
    if (!text) return;
    items.unshift({ id: ++_seq, ts: Date.now(), kind, text, resultId: opts.resultId || null });
    while (items.length > MAX) items.pop();
    renderActivity();
}

export function activityItems() { return items; }

export function renderActivity() {
    const el = document.getElementById('wb-activity');
    if (!el) return;
    el.textContent = '';
    if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'wb-empty';
        empty.textContent = t('act.empty');
        el.appendChild(empty);
        return;
    }
    items.forEach(it => {
        const row = document.createElement('div');
        row.className = `act-row act-${it.kind}`;
        const time = document.createElement('span');
        time.className = 'act-time';
        time.textContent = formatClock(it.ts, state.uiTimezone);
        const dot = document.createElement('span');
        dot.className = 'act-dot';
        const text = document.createElement('span');
        text.className = 'act-text';
        text.textContent = it.text;
        row.append(time, dot, text);
        if (it.resultId) {
            const btn = document.createElement('button');
            btn.className = 'act-link';
            btn.textContent = t('act.open');
            btn.addEventListener('click', () => {
                window.dispatchEvent(new CustomEvent('ak:open-result', { detail: { id: it.resultId } }));
            });
            row.appendChild(btn);
        }
        el.appendChild(row);
    });
}

/** WS 消息 → 动态。只收有意义的变化；行情 tick / 指标重算这类高频消息不进。 */
export function noteWs(msg) {
    const type = msg && msg.type;
    switch (type) {
        case 'indicator_add':
            addActivity('indicator', `${t('act.add_indicator')} ${msg.display_name || msg.inst_id || ''}`.trim());
            break;
        case 'indicator_remove':
            addActivity('indicator', `${t('act.remove_indicator')} ${msg.inst_id || ''}`.trim());
            break;
        case 'drawing_add':
            addActivity('drawing', `${t('act.add_drawing')} ${(msg.drawing && msg.drawing.type) || ''}`.trim());
            break;
        case 'drawing_remove':
            addActivity('drawing', t('act.remove_drawing'));
            break;
        case 'drawings_add':
            addActivity('drawing', `${t('act.drawings_add')} ${(msg.drawings || []).length}`);
            break;
        case 'drawings_remove':
            addActivity('drawing', `${t('act.drawings_remove')} ${(msg.ids || []).length}`);
            break;
        case 'board_create':
            addActivity('board', `${t('act.board_create')} ${(msg.board && (msg.board.name || msg.board.id)) || ''}`.trim());
            break;
        case 'board_remove':
            addActivity('board', t('act.board_remove'));
            break;
        case 'kline_source_set':
            addActivity('data', `${t('act.kline_source')} ${msg.script || ''}`.trim());
            break;
        case 'scripts_changed':
            addActivity('data', t('act.scripts_changed'));
            break;
        case 'result_created': {
            const r = msg.result || {};
            const pct = _fmtPct(r.stats && r.stats.total_return);
            addActivity('result', `${t('act.result_created')} ${r.display_name || r.result_id || ''} ${pct}`.trim(),
                { resultId: r.result_id });
            break;
        }
        case 'result_deleted':
            addActivity('result', t('act.result_deleted'), { resultId: null });
            break;
        case 'datasource_error':
            addActivity('error', `${t('act.ds_error')}: ${msg.error || ''}`.trim());
            break;
        default:
            break;
    }
}
