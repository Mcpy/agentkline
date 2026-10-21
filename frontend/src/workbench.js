// ============================================================
// 底部工作坞（v0.6.0）：概览 / 动态 / 调试
// 收起 = 32px 状态条；展开默认 380px，顶边可拖动调高；日志降级到隐藏的调试页
// ============================================================
import { state } from './state.js';
import { t } from './i18n.js';
import { renderActivity } from './activity.js';

const H_KEY = 'ak_wb_h';
const H_MIN = 140;
const H_DEFAULT = 380;
let _h = H_DEFAULT;
try {
    const saved = Number(localStorage.getItem(H_KEY));
    if (Number.isFinite(saved) && saved >= H_MIN) _h = saved;
} catch (e) { /* localStorage 不可用则用默认高度 */ }

let _open = false;
let _tab = 'activity';
let _bound = false;

function _maxH() { return Math.max(H_MIN, Math.round(window.innerHeight * 0.72)); }
function _clampH(h) { return Math.min(Math.max(Math.round(h), H_MIN), _maxH()); }

function _applyHeight() {
    const wb = document.getElementById('workbench');
    if (!wb) return;
    // 收起时交给 .collapsed 的 32px，展开才用拖出来的高度
    wb.style.height = _open ? `${_clampH(_h)}px` : '';
}

function _saveHeight() {
    try { localStorage.setItem(H_KEY, String(Math.round(_h))); } catch (e) { /* 忽略 */ }
}

function _debugEnabled() {
    try {
        return new URLSearchParams(location.search).get('debug') === '1'
            || localStorage.getItem('ak_debug') === '1';
    } catch (e) { return false; }
}

function _tabs() {
    return [...document.querySelectorAll('#wb-tabs .wb-tab')];
}

export function bindWorkbench() {
    if (_bound) return;
    _bound = true;
    const head = document.getElementById('wb-head');
    const toggle = document.getElementById('wb-toggle');
    if (toggle) toggle.addEventListener('click', (e) => { e.stopPropagation(); toggleWorkbench(); });
    if (head) head.addEventListener('click', (e) => {
        if (e.target.closest('.wb-tab')) return;
        toggleWorkbench();
    });
    _tabs().forEach(btn => btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setWorkbenchTab(btn.dataset.tab);
    }));
    const dbg = document.querySelector('#wb-tabs .wb-tab-debug');
    if (dbg) dbg.style.display = _debugEnabled() ? '' : 'none';
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && _open) closeWorkbench();
    });
    const grip = document.getElementById('wb-resize');
    if (grip) {
        let drag = null;
        grip.addEventListener('pointerdown', (e) => {
            if (e.button !== 0) return;
            drag = { y: e.clientY, h: _h };
            grip.setPointerCapture(e.pointerId);
            document.body.classList.add('wb-resizing');
            e.preventDefault();
        });
        grip.addEventListener('pointermove', (e) => {
            if (!drag) return;
            _h = _clampH(drag.h + (drag.y - e.clientY));
            _applyHeight();
        });
        const end = () => {
            if (!drag) return;
            drag = null;
            document.body.classList.remove('wb-resizing');
            _saveHeight();
        };
        grip.addEventListener('pointerup', end);
        grip.addEventListener('pointercancel', end);
        grip.addEventListener('dblclick', () => {
            _h = H_DEFAULT;
            _applyHeight();
            _saveHeight();
        });
    }
    window.addEventListener('resize', () => { if (_open) _applyHeight(); });
    // 左划回补走 Vela 原生 loadRange，不经过 WS：由 adapter 广播后刷新状态条
    window.addEventListener('ak:bars-changed', updateWorkbenchStatus);
    apply();
}

export function isWorkbenchOpen() { return _open; }

export function openWorkbench(tab) {
    _open = true;
    if (tab) _tab = tab;
    apply();
}

export function closeWorkbench() {
    _open = false;
    apply();
}

export function toggleWorkbench() {
    _open = !_open;
    apply();
}

export function setWorkbenchTab(tab) {
    _tab = tab;
    _open = true;
    apply();
}

export function renderWorkbench() { apply(); }

export function updateWorkbenchStatus() {
    const el = document.getElementById('wb-status');
    if (!el) return;
    // 0.6.0：状态条只承载「连接 + 现场」，结果信息统一由顶部结果栏呈现，避免两处重复。
    const board = (state.boards || []).find(b => b.id === state.currentBoard);
    const name = board ? (board.identity_display || board.name || board.id) : '—';
    const n = (state.ohlcv || []).length;
    const online = state.ws && state.ws.readyState === WebSocket.OPEN;
    el.className = 'wb-status';
    el.textContent = '';
    const dot = document.createElement('span');
    dot.className = `wb-dot ${online ? 'on' : 'off'}`;
    dot.textContent = online ? '●' : '○';
    // 0.6.0：状态条只留连接 + 现场 + 周期 + 根数；末根时间不再显示（用户反馈避免误读）。
    el.append(dot, document.createTextNode(
        ` ${online ? t('bar.connected') : t('bar.disconnected')} · ${name} · ${state.currentTimeframe || ''} · ${n} ${t('result.bars')}`));
}

function apply() {
    const wb = document.getElementById('workbench');
    const body = document.getElementById('wb-body');
    if (!wb || !body) return;
    const hasResult = !!(state.resultActive && (state.results || []).some(r => r.result_id === state.resultActive));
    if (_tab === 'overview' && !hasResult) _tab = 'activity';
    if (_tab === 'debug' && !_debugEnabled()) _tab = 'activity';
    wb.classList.toggle('collapsed', !_open);
    _applyHeight();
    body.style.display = _open ? '' : 'none';
    const toggle = document.getElementById('wb-toggle');
    if (toggle) toggle.textContent = _open ? '▼' : '▲';
    _tabs().forEach(btn => {
        const tab = btn.dataset.tab;
        if (tab === 'overview') btn.style.display = hasResult ? '' : 'none';
        btn.classList.toggle('active', _open && tab === _tab);
    });
    [...document.querySelectorAll('#wb-body .wb-pane')].forEach(p => {
        p.style.display = (_open && p.dataset.pane === _tab) ? '' : 'none';
    });
    updateWorkbenchStatus();
    if (_open && _tab === 'activity') renderActivity();
}
