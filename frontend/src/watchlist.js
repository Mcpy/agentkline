// ============================================================
// v0.4.1 雷达抽屉：跨板盯盘（quotes_update 驱动，无轮询 fetch）
// 行点击：有板=切现场；无板=一步建板即锁（复用搜索流建板语义）
// ============================================================
import { state } from './state.js';
import { log } from './log.js';
import { switchBoard } from './ui.js';
import { createBoardFor, openSearch } from './search.js';
import { showContextMenu } from './menu.js';

state.watch = { open: true, rows: [] };  // v0.4.1 优化：雷达默认开

const STATE_DOT = { visible: '#26a69a', hidden: '#787b86', watch: '#2962ff' };

export function bindWatchlist() {
    // WS→雷达钩子（断循环依赖：ws.js 不再 import 本模块）
    state.watchHooks = { quotes: applyQuotes, changed: applyQuotes };
    const tab = document.getElementById('radar-tab');
    if (tab) tab.onclick = () => toggleRadar(!state.watch.open);
    const wrap0 = document.getElementById('radar-wrap');
    if (wrap0) wrap0.classList.toggle('open', state.watch.open);  // 初始：雷达默认开
    syncWatchlist();  // 新连接首同步（WS 只推增量）
    renderWatchlist();
    const wsBtn = document.getElementById('watch-search');
    if (wsBtn) wsBtn.onclick = () => openSearch();
}

export async function removeRow(source, symbol) {
    // 乐观移除 + 服务端广播兜底其他客户端
    state.watch.rows = (state.watch.rows || []).filter(
        r => !(r.source === source && r.symbol === symbol));
    renderWatchlist();
    const r = await fetch(`/api/watchlist/rows?source=${encodeURIComponent(source)}&symbol=${encodeURIComponent(symbol)}`,
                          { method: 'DELETE' });
    if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || '移盯失败'); syncWatchlist(); }
}

export function syncWatchlist() {
    fetch('/api/watchlist').then(r => r.json())
        .then(d => applyQuotes((d.groups && d.groups[0] ? d.groups[0].rows : []) || []))
        .catch(() => {});
}

export function applyQuotes(rows) {
    state.watch.rows = rows || [];
    if (state.watch.open) renderWatchlist();
}

export function toggleRadar(open) {
    state.watch.open = !!open;
    const wrap = document.getElementById('radar-wrap');
    if (wrap) wrap.classList.toggle('open', state.watch.open);
    if (state.watch.open) syncWatchlist();
    renderWatchlist();
}

export function renderWatchlist() {
    const dw = document.getElementById('watch-drawer');
    if (!dw) return;
    if (!state.watch.open) return;
    const box = document.getElementById('watch-rows');
    box.innerHTML = '';
    if (!state.watch.rows.length) {
        box.innerHTML = '<div class="watch-empty">雷达空着。搜索行点"＋盯"、或板标签右键"加入雷达"。</div>';
        return;
    }
    state.watch.rows.forEach(r => {
        const div = document.createElement('div');
        div.className = 'watch-row';
        const pct = r.change_pct == null ? '' :
            `<span class="watch-pct" style="color:${r.change_pct >= 0 ? '#26a69a' : '#ef5350'}">${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%</span>`;
        div.innerHTML = `
            <span class="watch-dot" style="background:${STATE_DOT[r.state] || '#787b86'}" title="${r.state}"></span>
            <span class="watch-sym">${r.source.split('/')[1] || r.source}: ${r.symbol}</span>
            <span class="watch-price">${r.price == null ? '—' : r.price.toLocaleString()}</span>
            ${pct}
            <span class="watch-board">${r.has_board ? '●' : ''}</span>
            ${r.stale ? '<span class="watch-stale" title="连续取价失败">stale</span>' : ''}`;
        const x = document.createElement('span');
        x.className = 'watch-x'; x.textContent = '✕'; x.title = '移出雷达';
        x.onclick = (e) => { e.stopPropagation(); removeRow(r.source, r.symbol); };
        div.appendChild(x);
        div.oncontextmenu = (e) => {
            e.preventDefault(); e.stopPropagation();
            showContextMenu(e.clientX, e.clientY, [
                { label: '移出雷达', danger: true, onClick: () => removeRow(r.source, r.symbol) },
            ]);
        };
        div.onclick = async () => {
            if (r.has_board && r.board_id) { switchBoard(r.board_id); return; }
            const newId = await createBoardFor(r.symbol, r.source);
            if (newId) { switchBoard(newId); log('info', `雷达行一步建板并进入: ${r.symbol}`); }
        };
        box.appendChild(div);
    });
}
