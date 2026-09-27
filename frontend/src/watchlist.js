// ============================================================
// v0.4.2 雷达抽屉：分组 UI + 拖拽 + 过滤 + hover 卡
// 结构：state.watch.groups = [{id,name,rows:[行视图]}]；quotes_update 平面行按 key 合并
// 行点击：有板=切现场；无板=一步建板即锁（复用搜索流建板语义）
// ============================================================
import { state } from './state.js';
import { log } from './log.js';
import { switchBoard } from './ui.js';
import { createBoardFor, openSearch } from './search.js';
import { showContextMenu } from './menu.js';

state.watch = { open: true, groups: [], filter: '' };  // 雷达默认开（0.4.1 优化保留）

const STATE_DOT = { visible: '#26a69a', hidden: '#787b86', watch: '#2962ff' };
const LS_COLLAPSED = 'ak_watch_collapsed';

function collapsedMap() {
    try { return JSON.parse(localStorage.getItem(LS_COLLAPSED) || '{}'); } catch { return {}; }
}
function setCollapsed(gid, v) {
    const c = collapsedMap();
    if (v) c[gid] = 1; else delete c[gid];
    localStorage.setItem(LS_COLLAPSED, JSON.stringify(c));
}
const rowKey = r => `${r.source}|${r.symbol}`;
const fmtN = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }));

export function bindWatchlist() {
    // WS→雷达钩子（断循环依赖：ws.js 不 import 本模块）
    state.watchHooks = { quotes: applyQuotes, changed: applyStructure, resync: syncWatchlist };
    const tab = document.getElementById('radar-tab');
    if (tab) tab.onclick = () => toggleRadar(!state.watch.open);
    const wrap0 = document.getElementById('radar-wrap');
    if (wrap0) wrap0.classList.toggle('open', state.watch.open);
    const fi = document.getElementById('watch-filter');
    if (fi) fi.oninput = () => { state.watch.filter = fi.value || ''; renderWatchlist(); };
    const ag = document.getElementById('watch-addgroup');
    if (ag) ag.onclick = () => beginAddGroup();
    syncWatchlist();
    renderWatchlist();
    const wsBtn = document.getElementById('watch-search');
    if (wsBtn) wsBtn.onclick = () => openSearch();
}

// ---------- 数据面 ----------
export function applyStructure(groups) {
    state.watch.groups = (groups || []).map(g => ({ id: g.id, name: g.name, rows: g.rows || [] }));
    if (state.watch.open) renderWatchlist();
}

export function applyQuotes(rows) {
    // 平面行（quotes_update / watchlist_list 兼容）按 key 合并进组结构，保持组归属
    const m = new Map((rows || []).map(r => [rowKey(r), r]));
    let hit = false;
    (state.watch.groups || []).forEach(g => {
        g.rows = (g.rows || []).map(r => { const u = m.get(rowKey(r)); if (u) { hit = true; return u; } return r; });
    });
    if (!hit && !(state.watch.groups || []).length) applyStructure([{ id: 'default', name: '默认', rows: rows || [] }]);
    if (state.watch.open) renderWatchlist();
}

export function syncWatchlist() {
    fetch('/api/watchlist').then(r => r.json())
        .then(d => applyStructure(d.groups || []))
        .catch(() => {});
}

export async function removeRow(source, symbol) {
    // 乐观移除（全组遍历）+ 服务端广播兜底其他客户端
    (state.watch.groups || []).forEach(g => {
        g.rows = (g.rows || []).filter(r => !(r.source === source && r.symbol === symbol));
    });
    renderWatchlist();
    const r = await fetch(`/api/watchlist/rows?source=${encodeURIComponent(source)}&symbol=${encodeURIComponent(symbol)}`,
                          { method: 'DELETE' });
    if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || '移盯失败'); syncWatchlist(); }
}

export async function moveRow(source, symbol, toGroup, index) {
    // 乐观移组 + PUT move；失败回滚重同步
    const from = (state.watch.groups || []).find(g => (g.rows || []).some(r => r.source === source && r.symbol === symbol));
    const to = (state.watch.groups || []).find(g => g.id === toGroup);
    if (from && to) {
        const row = from.rows.find(r => r.source === source && r.symbol === symbol);
        from.rows = from.rows.filter(r => r !== row);
        const idx = index == null ? to.rows.length : Math.min(index, to.rows.length);
        to.rows.splice(idx, 0, row);
        renderWatchlist();
    }
    const r = await fetch('/api/watchlist/move', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, symbol, group_id: toGroup, index: index == null ? null : index }) });
    if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || '移组失败'); }
    syncWatchlist();
}

export function toggleRadar(open) {
    state.watch.open = !!open;
    const wrap = document.getElementById('radar-wrap');
    if (wrap) wrap.classList.toggle('open', state.watch.open);
    if (state.watch.open) syncWatchlist();
    renderWatchlist();
}

// ---------- 组管理 ----------
function beginAddGroup() {
    const box = document.getElementById('watch-rows');
    if (!box || box.querySelector('.wg-input')) return;
    const inp = document.createElement('input');
    inp.className = 'wg-input'; inp.placeholder = '组名，Enter 创建';
    box.prepend(inp); inp.focus();
    const done = async (ok) => {
        const name = (inp.value || '').trim();
        inp.remove();
        if (!ok || !name) return;
        const r = await fetch('/api/watchlist/groups', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }) });
        if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || '建组失败'); }
        syncWatchlist();
    };
    inp.onkeydown = e => { if (e.key === 'Enter') done(true); if (e.key === 'Escape') done(false); };
    inp.onblur = () => done(true);
}

async function renameGroup(g) {
    const name = window.prompt(`重命名分组「${g.name}」`, g.name);
    if (name == null || !name.trim() || name.trim() === g.name) return;
    const r = await fetch('/api/watchlist/groups/rename', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_id: g.id, name: name.trim() }) });
    if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || '重命名失败'); }
    syncWatchlist();
}

async function removeGroup(g) {
    if (!window.confirm(`删除分组「${g.name}」？\n组内 ${g.rows.length} 行将回落默认组（不删行）。`)) return;
    const r = await fetch(`/api/watchlist/groups?group_id=${encodeURIComponent(g.id)}`, { method: 'DELETE' });
    if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || '删组失败'); }
    syncWatchlist();
}

// ---------- 渲染 ----------
export function renderWatchlist() {
    const dw = document.getElementById('watch-drawer');
    if (!dw || !state.watch.open) return;
    const box = document.getElementById('watch-rows');
    if (!box) return;
    box.innerHTML = '';
    const groups = state.watch.groups || [];
    const f = (state.watch.filter || '').trim().toLowerCase();
    let total = 0;

    groups.forEach(g => {
        let rows = g.rows || [];
        if (f) rows = rows.filter(r =>
            (r.symbol || '').toLowerCase().includes(f) || (r.source || '').toLowerCase().includes(f));
        total += rows.length;
        if (f && !rows.length) return;  // 过滤态隐藏空组

        const sec = document.createElement('div');
        sec.className = 'watch-group';
        const coll = !f && collapsedMap()[g.id];

        const hd = document.createElement('div');
        hd.className = 'watch-group-head';
        hd.innerHTML = `<span class="wg-caret">${coll ? '▸' : '▾'}</span>`
            + `<span class="wg-name">${g.name}</span><span class="wg-count">${rows.length}</span>`
            + (g.id !== 'default' ? '<span class="wg-menu" title="组管理">⋮</span>' : '');
        hd.onclick = (e) => {
            if (e.target.classList.contains('wg-menu')) return;
            if (f) return;  // 过滤态不折叠
            setCollapsed(g.id, !collapsedMap()[g.id]);
            renderWatchlist();
        };
        const menu = hd.querySelector('.wg-menu');
        if (menu) menu.onclick = (e) => {
            e.stopPropagation();
            showContextMenu(e.clientX, e.clientY, [
                { label: '重命名…', onClick: () => renameGroup(g) },
                { label: '删除组（行回落默认组）', danger: true, onClick: () => removeGroup(g) },
            ]);
        };

        const rowsEl = document.createElement('div');
        rowsEl.className = 'watch-group-rows';
        rowsEl.dataset.gid = g.id;
        if (!coll) rows.forEach(r => rowsEl.appendChild(rowEl(r, g)));
        // 拖拽投放区
        rowsEl.ondragover = e => { e.preventDefault(); rowsEl.classList.add('drop-on'); };
        rowsEl.ondragleave = () => rowsEl.classList.remove('drop-on');
        rowsEl.ondrop = async e => {
            e.preventDefault(); rowsEl.classList.remove('drop-on');
            let d = {}; try { d = JSON.parse(e.dataTransfer.getData('text/plain') || '{}'); } catch {}
            if (!d.source) return;
            const rowEls = [...rowsEl.querySelectorAll('.watch-row:not(.dragging)')];
            let idx = rowEls.length;
            for (let i = 0; i < rowEls.length; i++) {
                const b = rowEls[i].getBoundingClientRect();
                if (e.clientY < b.top + b.height / 2) { idx = i; break; }
            }
            await moveRow(d.source, d.symbol, g.id, idx);
        };

        sec.append(hd, rowsEl);
        box.appendChild(sec);
    });

    if (!total) {
        box.innerHTML = `<div class="watch-empty">${f ? '无匹配行。' :
            '雷达空着。搜索行点"＋盯"、或板标签右键"加入雷达"。'}</div>`;
    }
}

function rowEl(r, g) {
    const div = document.createElement('div');
    div.className = 'watch-row';
    div.draggable = true;
    const pct = r.change_pct == null ? '' :
        `<span class="watch-pct" style="color:${r.change_pct >= 0 ? '#26a69a' : '#ef5350'}">${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%</span>`;
    div.innerHTML = `
        <span class="watch-dot" style="background:${STATE_DOT[r.state] || '#787b86'}" title="${r.state}"></span>
        <span class="watch-sym">${r.source.split('/')[1] || r.source}: ${r.symbol}</span>
        <span class="watch-price">${r.price == null ? '—' : r.price.toLocaleString()}</span>
        ${pct}
        <span class="watch-board">${r.has_board ? '●' : ''}</span>
        ${r.stale ? '<span class="watch-stale" title="连续取价失败">stale</span>' : ''}`;
    // hover 卡：24h 高/低/量（quote.extra 白捡数据；无 extra 不显示）
    if (r.extra && (r.extra.high != null || r.extra.low != null)) {
        const card = document.createElement('div');
        card.className = 'watch-extra';
        card.textContent = `24h 高 ${fmtN(r.extra.high)} · 低 ${fmtN(r.extra.low)}`
            + (r.extra.quote_volume != null ? ` · 量 ${fmtN(r.extra.quote_volume)}` : '');
        div.appendChild(card);
    }
    const x = document.createElement('span');
    x.className = 'watch-x'; x.textContent = '✕'; x.title = '移出雷达';
    x.onclick = (e) => { e.stopPropagation(); removeRow(r.source, r.symbol); };
    div.appendChild(x);
    div.ondragstart = e => {
        e.dataTransfer.setData('text/plain', JSON.stringify({ source: r.source, symbol: r.symbol }));
        e.dataTransfer.effectAllowed = 'move';
        div.classList.add('dragging');
    };
    div.ondragend = () => div.classList.remove('dragging');
    div.oncontextmenu = (e) => {
        e.preventDefault(); e.stopPropagation();
        const items = [{ label: '移出雷达', danger: true, onClick: () => removeRow(r.source, r.symbol) }];
        (state.watch.groups || []).forEach(gg => {
            if (gg.id !== g.id) items.push({ label: `移到组 ▸ ${gg.name}`, onClick: () => moveRow(r.source, r.symbol, gg.id, null) });
        });
        showContextMenu(e.clientX, e.clientY, items);
    };
    div.onclick = async () => {
        if (r.has_board && r.board_id) { switchBoard(r.board_id); return; }
        const newId = await createBoardFor(r.symbol, r.source);
        if (newId) { switchBoard(newId); log('info', `雷达行一步建板并进入: ${r.symbol}`); }
    };
    return div;
}
