import { state } from './state.js';
import { log } from './log.js';

    // ============================================================
    // 标的搜索流（P1）：搜索弹层 → 点行 = 一步建板即锁
    // 行 = 完整二元组 (源, 裸符号)；● = 已有现场（点击直跳，防重复建板）
    // ============================================================
    let _debounce = null;

    function _el(id) { return document.getElementById(id); }

    export function openSearch(prefill = '') {
        const ov = _el('search-overlay');
        ov.style.display = 'flex';
        const input = _el('search-input');
        input.value = prefill;
        input.focus();
        runQuery(prefill);
    }

    export function closeSearch() {
        _el('search-overlay').style.display = 'none';
    }

    export function bindSearch() {
        const input = _el('search-input');
        input.addEventListener('input', () => {
            clearTimeout(_debounce);
            _debounce = setTimeout(() => runQuery(input.value), 300);
        });
        input.addEventListener('keydown', e => {
            if (e.key === 'Escape') closeSearch();
        });
        _el('search-close').addEventListener('click', closeSearch);
        _el('search-overlay').addEventListener('click', e => {
            if (e.target === _el('search-overlay')) closeSearch();
        });
    }

    async function runQuery(q) {
        const box = _el('search-results');
        q = (q || '').trim();
        box.innerHTML = '<div class="search-row hint">搜索中…</div>';
        // 高级输入：@源名 裸符号 → 直达行（无徽章源也能配）
        if (q.startsWith('@')) {
            const m = q.slice(1).match(/^(\S+)\s+(.*)$/);
            if (m) {
                renderRows([{ symbol: m[2], source: `datasource/${m[1]}`, display: m[2], has_board: false }]);
                return;
            }
        }
        try {
            const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
            const d = await r.json();
            if (!d.rows || d.rows.length === 0) {
                box.innerHTML = '<div class="search-row hint">无匹配（索引=CAPS.symbols 源；无徽章源用 @源名 裸符号）</div>';
                return;
            }
            renderRows(d.rows);
        } catch (e) {
            box.innerHTML = `<div class="search-row hint">搜索失败: ${e.message}</div>`;
        }
    }

    function renderRows(rows) {
        const box = _el('search-results');
        box.innerHTML = '';
        rows.forEach(row => {
            const div = document.createElement('div');
            div.className = 'search-row';
            div.innerHTML = `<span class="sr-symbol">${row.display || row.symbol}</span>
                <span class="sr-source">${row.source}</span>
                <span class="sr-badge">${row.has_board ? '● 已有现场' : ''}</span>`;
            div.addEventListener('click', () => pickRow(row));
            box.appendChild(div);
        });
    }

    async function pickRow(row) {
        // ● 已有现场 → 直跳（三态分发的单板态；多板态=雷达 0.4.1）
        if (row.has_board) {
            const b = state.boards.find(b => {
                const lk = state.locks[b.id] || {};
                return lk.script === row.source
                    && ((lk.identity || {}).symbol === row.symbol);
            });
            if (b) {
                await fetch(`/api/board/${b.id}`);  // 服务端广播 board_switch
                closeSearch();
                return;
            }
        }
        const id = 'b_' + String(row.symbol).replace(/[^a-zA-Z0-9]+/g, '_').toLowerCase()
            + '_' + Date.now().toString(36);
        const res = await fetch('/api/board', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, symbol: row.symbol, source: row.source,
                                   params: { symbol: row.symbol }, poll_s: 5 }),
        });
        if (res.status === 409) {
            toastLocked(await res.json());
            return;
        }
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            toast(`建板失败: ${d.detail || res.status}`);
            return;
        }
        await fetch(`/api/board/${id}`);  // 进入新现场
        closeSearch();
        log('info', `搜索建板即锁: ${id} ← ${row.symbol}@${row.source}`);
    }

    // ============ 撞锁 Toast + 一键改道（摩擦面 B） ============
    export function toastLocked(detail) {
        const sug = (detail && detail.suggestion) || {};
        toast(detail?.error || 'SOURCE_LOCKED', '用此配置新建画板', async () => {
            const id = 'b_' + String(sug.symbol || 'x').replace(/[^a-zA-Z0-9]+/g, '_').toLowerCase()
                + '_' + Date.now().toString(36);
            const res = await fetch('/api/board', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, symbol: sug.symbol, source: sug.script,
                                       params: sug.params || { symbol: sug.symbol }, poll_s: 5 }),
            });
            if (res.ok) {
                await fetch(`/api/board/${id}`);
                closeSearch();
            } else {
                const d = await res.json().catch(() => ({}));
                toast(`改道建板失败: ${d.detail || res.status}`);
            }
        });
    }

    export function toast(msg, actionLabel, actionFn) {
        const wrap = _el('toast-wrap');
        const t = document.createElement('div');
        t.className = 'toast';
        const span = document.createElement('span');
        span.textContent = msg;
        t.appendChild(span);
        if (actionLabel) {
            const btn = document.createElement('button');
            btn.className = 'btn-primary';
            btn.textContent = actionLabel;
            btn.addEventListener('click', () => { t.remove(); actionFn && actionFn(); });
            t.appendChild(btn);
        }
        wrap.appendChild(t);
        setTimeout(() => t.remove(), 8000);
    }
