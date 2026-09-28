import { state } from './state.js';
import { log } from './log.js';
import { showContextMenu } from './menu.js';

    // ============================================================
    // 标的搜索流（P1）：搜索弹层 → 点行 = 一步建板即锁
    // 行 = 完整二元组 (源, 裸符号)；● = 已有现场（点击直跳，防重复建板）
    // ============================================================
    let _debounce = null;
    let _srcFilter = null;   // v0.4.4 源筛选 chips
    let _srcList = null;

    function _el(id) { return document.getElementById(id); }

    export function openSearch(prefill = '') {
        const ov = _el('search-overlay');
        ov.style.display = 'flex';
        ensureSrcBtn();
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

    async function runQuery(q, opts = {}) {
        lastQuery = q;
        const box = _el('search-results');
        q = (q || '').trim();
        box.innerHTML = '<div class="search-row hint">搜索中…（首次使用需建索引，约 5-10s）</div>';
        // 高级输入：@源名 裸符号 → 直达行（无徽章源也能配）
        if (q.startsWith('@')) {
            const m = q.slice(1).match(/^(\S+)\s+(.*)$/);
            if (m) {
                renderRows([{ symbol: m[2], source: `datasource/${m[1]}`, display: m[2], has_board: false }]);
                return;
            }
        }
        try {
            const srcQ = _srcFilter ? `&source=${encodeURIComponent(_srcFilter)}` : '';
            const rfQ = opts.refresh ? '&refresh=true' : '';
            const ctl = new AbortController();  // v0.4.4：20s 超时防烂网转圈 forever
            const timer = setTimeout(() => ctl.abort(), 20000);
            let r;
            try {
                r = await fetch(`/api/search?q=${encodeURIComponent(q)}${srcQ}${rfQ}`, { signal: ctl.signal });
            } finally {
                clearTimeout(timer);
            }
            const d = await r.json();
            if (d.sources) setSrcList(d.sources);
            if (!d.rows || d.rows.length === 0) {
                box.innerHTML = '<div class="search-row hint">无匹配（索引=CAPS.symbols 源；无徽章源用 @源名 裸符号）</div>';
                return;
            }
            renderRows(d.rows);
        } catch (e) {
            const msg = e.name === 'AbortError'
                ? '搜索超时（索引构建中或源网络限流窗）——请稍后重试'
                : `搜索失败: ${e.message}`;
            box.innerHTML = `<div class="search-row hint">${msg}</div>`;
        }
    }

    // v0.4.4 源筛选 = 搜索框行左侧下拉按钮（源多也不排串；复用右键菜单组件）
    function ensureSrcBtn() {
        if (_el('search-srcbtn')) return;
        const input = _el('search-input');
        const head = document.createElement('div');
        head.className = 'search-head';
        input.parentNode.insertBefore(head, input);
        const btn = document.createElement('button');
        btn.id = 'search-srcbtn'; btn.className = 'src-btn';
        const rf = document.createElement('button');
        rf.id = 'search-refresh'; rf.className = 'src-refresh';
        rf.innerHTML = '<span class="rf-ic">⟳</span>';  // 图标独立 span：旋转只转图标不转按钮框
        rf.title = '重建搜索索引（手动刷新）';
        rf.onclick = (e) => {
            e.stopPropagation();
            if (rf.classList.contains('spinning')) return;
            rf.classList.add('spinning');
            runQuery(lastQuery, { refresh: true }).finally(() => rf.classList.remove('spinning'));
        };
        head.append(btn, input, rf);
        updateSrcBtn();
        btn.onclick = (e) => {
            e.stopPropagation();  // 防全局 document click 关闭刚弹出的菜单
            const r = btn.getBoundingClientRect();
            const items = [{ label: '全部源', onClick: () => pickSrc(null) }];
            (_srcList || []).forEach(x => items.push({ label: x.display, onClick: () => pickSrc(x.id) }));
            showContextMenu(r.left, r.bottom + 4, items);
        };
    }

    function pickSrc(id) {
        _srcFilter = id;
        updateSrcBtn();
        runQuery(lastQuery);
    }

    function updateSrcBtn() {
        const btn = _el('search-srcbtn'); if (!btn) return;
        const cur = (_srcList || []).find(x => x.id === _srcFilter);
        btn.textContent = cur ? `源: ${cur.display} ▾` : '源: 全部 ▾';
    }

    // 源清单随 search 响应附带的 sources 字段（不另开端点）
    function setSrcList(ids) {
        _srcList = (ids || []).map(id => ({ id, display: id.split('/')[1] }));
        updateSrcBtn();
    }

    function renderRows(rows) {
        const box = _el('search-results');
        box.innerHTML = '';
        rows.forEach(row => {
            const div = document.createElement('div');
            div.className = 'search-row';
            div.dataset.key = `${row.source}|${row.symbol}`;
            div.innerHTML = `<span class="sr-symbol">${row.display || row.symbol}</span>
                <span class="sr-source">${row.source}</span>
                <span class="sr-badge">${row.has_board ? '● 已有现场' : ''}</span>
                <span class="sr-watch ${row.watched ? 'on' : ''}" title="${row.watched ? '已在雷达：点击取消盯盘' : '加入雷达盯盘'}">${row.watched ? '盯盘中' : '＋盯'}</span>`;
            div.querySelector('.sr-watch').addEventListener('click', async (e) => {
                e.stopPropagation();
                if (row.watched) {   // 取消盯盘：DELETE 走 query
                    const url = `/api/watchlist/rows?source=${encodeURIComponent(row.source)}&symbol=${encodeURIComponent(row.symbol)}`;
                    const r = await fetch(url, { method: 'DELETE' });
                    if (!r.ok) { const d = await r.json().catch(() => ({})); toast(d.detail || '操作失败'); }
                    else refreshSearch();
                    return;
                }
                // v0.4.2：多组时弹组选择；单组直接进默认组
                const gs = state.watch.groups || [];
                if (gs.length > 1) {
                    showContextMenu(e.clientX, e.clientY, gs.map(g => ({
                        label: `＋盯 · ${g.name}`, onClick: () => doWatchAdd(row, g.id) })));
                    return;
                }
                await doWatchAdd(row, null);
            });
            div.addEventListener('click', () => pickRow(row));
            box.appendChild(div);
        });
    }

    let lastBoardId = null;
    let lastQuery = '';  // 最近一次搜索词（refreshSearch 用）
    const inflight = new Set();

    async function doWatchAdd(row, groupId) {
        const r = await fetch('/api/watchlist/rows', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: row.source, symbol: row.symbol,
                                   ...(groupId ? { group_id: groupId } : {}) }) });
        if (!r.ok) { const d = await r.json().catch(() => ({})); toast(d.detail || '操作失败'); }
        else refreshSearch();   // 行内盯盘态即时翻转
    }

    export function refreshSearch() {
        if (_el('search-overlay').style.display !== 'none') runQuery(lastQuery);
    }

    function setRowLoading(row, on) {
        const div = document.querySelector(`.search-row[data-key="${row.source}|${row.symbol}"]`);
        if (!div) return;
        const badge = div.querySelector('.sr-badge');
        if (on) {
            div.classList.add('creating');
            badge.innerHTML = '<span class="sr-spin"></span> 正在创建现场…';
        } else {
            div.classList.remove('creating');
            badge.innerHTML = row.has_board ? '● 已有现场' : '';
        }
    }

    export async function createBoardFor(symbol, source) {
        const id = 'b_' + String(symbol).replace(/[^a-zA-Z0-9]+/g, '_').toLowerCase()
            + '_' + Date.now().toString(36);
        const res = await fetch('/api/board', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, symbol, source, params: { symbol }, poll_s: 5 }),
        });
        if (res.status === 409) { toastLocked(await res.json()); return null; }
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            toast(`建板失败: ${d.detail || res.status}`);
            return null;
        }
        const d = await res.json().catch(() => ({}));
        lastBoardId = d.id || id;
        return { id: lastBoardId, existing: !!d.existing };
    }

    async function pickRow(row) {
        const key = `${row.source}|${row.symbol}`;
        if (inflight.has(key)) return;            // in-flight 锁：连点不产重复请求
        inflight.add(key);
        setRowLoading(row, true);
        try {
            await _pickRowInner(row);
        } finally {
            inflight.delete(key);
            setRowLoading(row, false);
        }
    }

    async function _pickRowInner(row) {
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
        const r2 = await createBoardFor(row.symbol, row.source);
        if (r2) {
            refreshSearch();   // 行徽标动态变"● 已有现场"（弹层保持开，用户亲眼看到加载→完成）
            await fetch(`/api/board/${r2.id}`);  // 背后进入新现场；弹层不抢关，Esc/关闭或再点行离开
            log('info', `搜索建板即锁: ${r2.id} ← ${row.symbol}@${row.source}`);
        }
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
