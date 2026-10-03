// ============================================================================
// render.js —— v0.5 薄壳：应用层胶水（DOM/统计/指标栏/图例/上报/铭牌）保留，
// 图表语义面全委托 vela_adapter（R2 纪律：本文件不摸 window.Vela）。
// 退役：LWC 建图/副图独立 chart/十字线手动同步/自绘最新价标签/画线 series 渲染。
// ============================================================================
import { state } from './state.js';
import { openSearch } from './search.js';
import { isIntraday, formatTimeCN } from './format.js';
import { log } from './log.js';
import { openSettings } from './settings.js';
import { t, localizeBoardName } from './i18n.js';
import { showContextMenu } from './menu.js';
import {
    renderChartCore, applyDataUpdateCore, updateIndicatorSeriesCore,
    syncDrawings as adapterSyncDrawings, setVisibleTimeRangeCore, resizeAllChartsCore,
    captureSnapshotCore, onViewport, getVisibleTimeRange, readDataWindow,
} from './vela_adapter.js';

// ============ 活体注册表（resize 用；Vela 单图） ============
export function resizeAllCharts() { resizeAllChartsCore(); }

// ============ 应用层小工具 ============
function displayName(ind) { return (ind && ind.display_name) || (ind && ind.name) || ''; }

function updateDataInfo() {
    document.getElementById('data-info').textContent =
        `${(state.ohlcv || []).length} bars | ${Object.keys(state.indicators || {}).length} indicators`;
}

function getIndicatorColor(ind) {
    if (ind.style && ind.style.color) return ind.style.color;
    if (ind.lines && ind.lines.length > 0 && ind.lines[0].style && ind.lines[0].style.color) {
        return ind.lines[0].style.color;
    }
    return '#4fc3f7';
}

// ============ 指标栏（chip 显隐/设置/删除/内置菜单） ============
function renderIndicatorBar() {
    const bar = document.getElementById('indicator-bar');
    if (!bar) return;
    bar.innerHTML = `<span class="label">${t('bar.indicators')}</span>`;
    const addBtn = document.createElement('span');
    addBtn.className = 'ind-add';
    addBtn.textContent = t('bar.add_indicator');
    addBtn.title = t('ind.menu_title');
    addBtn.onclick = (e) => { e.stopPropagation(); openIndicatorMenu(e); };
    bar.appendChild(addBtn);

    const names = Object.keys(state.indicators || {});
    if (names.length === 0) {
        const empty = document.createElement('span');
        empty.style.cssText = 'font-size:11px;color:#555;';
        empty.textContent = t('ind.none');
        bar.appendChild(empty);
        return;
    }
    names.forEach(name => {
        const ind = state.indicators[name];
        const visible = state.visibility[name] !== false;
        const chip = document.createElement('div');
        chip.className = `ind-chip ${visible ? '' : 'hidden'}`;
        chip.title = t('ind.toggle_hint');
        const dot = document.createElement('span');
        dot.className = 'dot';
        dot.style.background = getIndicatorColor(ind);
        chip.appendChild(dot);
        const txt = document.createElement('span');
        txt.className = 'name';
        let label = displayName(ind);
        if (ind.subplot) label += t('ind.subplot_tag');
        if (ind.scope === 'timeframe') label += t('ind.scope_tag');
        txt.textContent = label;
        chip.appendChild(txt);
        const eye = document.createElement('span');
        eye.className = 'eye';
        eye.textContent = visible ? '👁' : '🚫';
        chip.appendChild(eye);
        const gear = document.createElement('span');
        gear.className = 'gear';
        gear.textContent = '⚙';
        gear.title = t('ind.settings');
        gear.onclick = (e) => { e.stopPropagation(); openSettings(name); };
        chip.appendChild(gear);
        chip.onclick = () => toggleIndicator(name);
        chip.oncontextmenu = (e) => {
            e.preventDefault(); e.stopPropagation();
            showContextMenu(e.clientX, e.clientY, [
                { label: t('ind.settings'), onClick: () => openSettings(name) },
                { label: t('ind.delete'), danger: true, onClick: () => deleteIndicator(name) },
            ]);
        };
        bar.appendChild(chip);
    });
}

function toggleIndicator(name) {
    const nowVisible = state.visibility[name] === false;
    state.visibility[name] = nowVisible;
    updateIndicatorSeries(name);        // adapter 重 emit（visible 标志随 spec 走）
    renderIndicatorBar();
    log('info', t('ind.toggled', { name, st: nowVisible ? t('ind.shown') : t('ind.hidden') }));
}

function deleteIndicator(name) {
    const url = `/api/indicator/${encodeURIComponent(name)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`;
    fetch(url, { method: 'DELETE' })
        .then(r => r.json())
        .then(d => { if (d.error) log('error', t('ind.delete_fail', { e: d.error })); });
}

const BUILTIN_INDICATORS = [
    { ref: 'indicator/sma',  label: t('ind.ma'),   group: t('ind.mainpane') },
    { ref: 'indicator/ema',  label: t('ind.ema'),  group: t('ind.mainpane') },
    { ref: 'indicator/bb',   label: t('ind.boll'), group: t('ind.mainpane') },
    { ref: 'indicator/sar',  label: t('ind.sar'),  group: t('ind.mainpane') },
    { ref: 'indicator/macd', label: 'MACD',        group: t('ind.subpane') },
    { ref: 'indicator/kdj',  label: 'KDJ',         group: t('ind.subpane') },
    { ref: 'indicator/rsi',  label: 'RSI',         group: t('ind.subpane') },
    { ref: 'indicator/obv',  label: 'OBV',         group: t('ind.subpane') },
];
function _instsOf(ref) {
    return Object.entries(state.indicators || {}).filter(([, i]) => (i.script || '') === ref).map(([id]) => id);
}
function openIndicatorMenu(e) {
    if (!state.currentBoard) { log('info', t('ind.need_board')); return; }
    showContextMenu(e.clientX, e.clientY, BUILTIN_INDICATORS.map(b => ({
        label: `${_instsOf(b.ref).length ? '✓ ' : '　'}[${b.group}] ${b.label}`,
        onClick: () => toggleBuiltin(b.ref),
    })));
}
async function toggleBuiltin(ref) {
    const insts = _instsOf(ref);
    if (insts.length) {
        for (const id of insts) {
            const r = await fetch(`/api/indicator/${encodeURIComponent(id)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`, { method: 'DELETE' });
            if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || t('ind.delete_fail_short')); }
        }
        return;
    }
    const r = await fetch('/api/indicator', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ board_id: state.currentBoard, timeframe: state.currentTimeframe, script: ref }) });
    if (!r.ok) { const d = await r.json().catch(() => ({})); log('error', d.detail || t('ind.add_fail')); }
}

// ============ 渲染入口（rAF 节流 + 引导/空态分支 + 委托 adapter） ============
let renderScheduled = false;
export function renderChart() {
    if (renderScheduled) return;
    renderScheduled = true;
    requestAnimationFrame(() => { renderScheduled = false; _doRender(); });
}
function _doRender() {
    try { _renderInner(); } catch (e) { log('error', t('chart.render_err', { e: e.message })); console.error(e); }
}
function _renderInner() {
    const container = document.getElementById('main-chart');
    const emptyState = document.getElementById('empty-state');
    const guide = document.getElementById('guide');
    if (!state.boards || state.boards.length === 0) {
        guide.style.display = 'block';
        emptyState.style.display = 'none';
        container.innerHTML = '';
        _clearSubplotDom();
        renderIndicatorBar(); updateDataInfo();
        return;
    }
    guide.style.display = 'none';
    if (!state.ohlcv || state.ohlcv.length === 0) {
        emptyState.style.display = 'block';
        container.innerHTML = '';
        _clearSubplotDom();
        renderIndicatorBar(); updateDataInfo();
        return;
    }
    emptyState.style.display = 'none';
    state.timeIndex = new Map(state.ohlcv.map((bar, i) => [Math.floor(bar.timestamp / 1000), i]));
    renderChartCore();                 // Vela 建图（adapter）
    _clearSubplotDom();                // 副图 DOM 标题条退役（Vela pane 原生标题）
    renderIndicatorBar();
    updateDataInfo();
    updateLegends(null);
    reportView();
}
function _clearSubplotDom() {
    const c = document.getElementById('subplots');
    if (c) c.innerHTML = '';
    state.subplotDivs = {};
    state.volDiv = null;
}

// ============ 增量更新 ============
export function applyDataUpdate(shift = 0) {
    applyDataUpdateCore(shift);
    updateDataInfo();
    reportView();
    updateLegends(null);
}
export function updateIndicatorSeries(instId) { updateIndicatorSeriesCore(instId); }
export function syncDrawings() { adapterSyncDrawings(); }
export function renderSubplots() { _clearSubplotDom(); updateLegends(null); }   // pane 由 adapter native 实例管理

// ============ 视口上报（/api/view） ============
let viewReportTimer = null;
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        fetch('/api/view', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
    } else reportView();
});
onViewport(() => reportView());
function reportView() {
    clearTimeout(viewReportTimer);
    viewReportTimer = setTimeout(() => {
        if (!state.ohlcv || !state.ohlcv.length) return;
        const r = getVisibleTimeRange();
        if (!r) return;
        const n = state.ohlcv.length;
        let fromIdx = 0, toIdx = n - 1;
        for (let i = 0; i < n; i++) { if (state.ohlcv[i].timestamp >= r.from) { fromIdx = i; break; } }
        for (let i = n - 1; i >= 0; i--) { if (state.ohlcv[i].timestamp <= r.to) { toIdx = i; break; } }
        fetch('/api/view', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                board_id: state.currentBoard, timeframe: state.currentTimeframe,
                from_time: state.ohlcv[fromIdx].timestamp, to_time: state.ohlcv[toIdx].timestamp,
                bars: toIdx - fromIdx + 1,
            }) }).catch(() => {});
    }, 500);
}

// ============ 历史回溯（左滚触发；Vela viewport:changed 桥 + 手势门） ============
let historyLoading = false;
let userTouched = false;
document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('main-chart');
    if (!container) return;
    ['wheel', 'pointerdown', 'touchstart'].forEach(ev =>
        container.addEventListener(ev, () => { userTouched = true; }, { passive: true }));
});
onViewport(() => {
    if (!userTouched) return;
    const r = getVisibleTimeRange();
    if (!r || !state.ohlcv || !state.ohlcv.length) return;
    if (state.ohlcv[0] && r.from <= state.ohlcv[0].timestamp + 2 * 86400e3) loadMoreHistory();
});
async function loadMoreHistory() {
    if (historyLoading || !state.currentBoard || !state.currentTimeframe) return;
    historyLoading = true;
    try {
        const r = await fetch(`/api/board/${state.currentBoard}/timeframe/${state.currentTimeframe}/backfill`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: 200 }) });
        const d = await r.json();
        if (d.prepended > 0) log('info', t('chart.backfill_ok', { n: d.prepended }));
    } catch (e) { log('error', t('chart.backfill_fail', { e: e.message })); }
    finally { historyLoading = false; }
}

// ============ 图例（自绘 DOM；十字线跟随 = container mousemove → dataWindowReadout 桥） ============
function fmtP(v) { return (v == null || !isFinite(v)) ? '--' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtC(v) { if (v == null || !isFinite(v)) return '--'; const a = Math.abs(v);
    if (a >= 1e8) return (v / 1e8).toFixed(2) + t('fmt.yi'); if (a >= 1e4) return (v / 1e4).toFixed(2) + t('fmt.wan');
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }); }
function boardLabel() {
    const bd = (state.boards || []).find(b => b.id === state.currentBoard);
    return localizeBoardName((bd && (bd.name || bd.identity_display)) || state.currentBoard || '');
}
function legendIndex(timeSec) {
    if (timeSec != null && state.timeIndex) { const i = state.timeIndex.get(timeSec); if (i !== undefined) return i; }
    return (state.ohlcv || []).length - 1;
}
function ensureLegendEl(key, host, sub) {
    if (!host) return null;
    state.legendEls = state.legendEls || {};
    let el = state.legendEls[key];
    if (!el || !el.isConnected) {
        el = document.createElement('div');
        el.className = 'legend' + (sub ? ' sub' : '');
        host.appendChild(el);
        state.legendEls[key] = el;
    }
    return el;
}
function indLegendHtml(ind, i) {
    const dot = (c) => `<span class="dot" style="background:${c}"></span>`;
    if (ind.lines && ind.lines.length) {
        return ind.lines.map(l => {
            const c = (l.style && l.style.color) || '#4fc3f7';
            return `<span class="lg">${dot(c)}${l.name} <b>${fmtP(l.values ? l.values[i] : null)}</b></span>`;
        }).join('');
    }
    const c = (ind.style && ind.style.color) || '#4fc3f7';
    return `<span class="lg">${dot(c)}${displayName(ind)} <b>${fmtP(ind.values ? ind.values[i] : null)}</b></span>`;
}
function setLegend(key, host, sub, rows, maxRows) {
    const el = ensureLegendEl(key, host, sub);
    if (!el) return;
    el.classList.toggle('inline', rows.length > maxRows);
    el.innerHTML = rows.map(r => `<div class="row">${r}</div>`).join('');
}
export function updateLegends(timeSec) {
    const i = legendIndex(timeSec);
    const b = (state.ohlcv || [])[i];
    const mainRows = [];
    if (b) {
        const prev = state.ohlcv[i - 1] || b;
        const chg = prev.close ? (b.close - prev.close) / prev.close * 100 : 0;
        const cls = b.close >= b.open ? 'up' : 'down';
        mainRows.push(`<span class="sym">${boardLabel()} · ${state.currentTimeframe || ''}</span>`
            + `<span>O <b>${fmtP(b.open)}</b></span><span>H <b>${fmtP(b.high)}</b></span>`
            + `<span>L <b>${fmtP(b.low)}</b></span><span>C <b class="${cls}">${fmtP(b.close)}</b></span>`
            + `<span class="${chg >= 0 ? 'up' : 'down'}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>`);
        Object.values(state.indicators || {}).forEach(ind => { if (!ind.subplot) mainRows.push(indLegendHtml(ind, i)); });
    }
    setLegend('main', document.getElementById('main-chart'), false, mainRows, 6);
    // 成交量行
    setLegend('volume', state.volDiv, true,
        b ? [`<span class="lg">VOL <b class="${b.close >= b.open ? 'up' : 'down'}">${fmtC(b.volume)}</b></span>`] : [], 1);
    // 副图行（Vela pane 无自绘 div：图例挂主图容器下缘，sub 样式）
    Object.keys(state.subplots || {}).forEach(name => {
        const rows = [];
        Object.values(state.indicators || {}).forEach(ind => { if (ind.subplot === name) rows.push(indLegendHtml(ind, i)); });
        setLegend('subplot_' + name, document.getElementById('main-chart'), true, rows, 2);
    });
}
// 十字线跟随桥：mousemove → readDataWindow → 时间反查 idx
(function bindLegendHover() {
    document.addEventListener('mousemove', (e) => {
        const host = document.getElementById('main-chart');
        if (!host || !host.contains(e.target)) { return; }
        const rw = readDataWindow();
        if (!rw || !rw.date) { return; }
        // readout.date = 'YYYY-MM-DD'（+time）→ 反查 timeIndex（秒键）
        const sec = Date.parse(rw.date + (rw.time ? 'T' + rw.time : 'T00:00') + 'Z') / 1000;
        updateLegends(isFinite(sec) ? Math.floor(sec) : null);
    }, { passive: true });
    document.addEventListener('mouseleave', () => updateLegends(null));
})();

// ============ 截图（snapshot_request） ============
export function captureSnapshot() {
    const dataUrl = captureSnapshotCore();
    if (!dataUrl) return;
    // 图例覆盖层合成（自绘 legend DOM 不在 canvas 内）
    fetch(dataUrl).then(r => r.blob()).then(blob => createImageBitmap(blob)).then(bmp => {
        const canvas = document.createElement('canvas');
        canvas.width = bmp.width; canvas.height = bmp.height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(bmp, 0, 0);
        const legend = document.querySelector('#main-chart .legend');
        if (legend) {
            ctx.font = '12px -apple-system, "Segoe UI", sans-serif';
            ctx.fillStyle = '#d1d4dc'; ctx.textBaseline = 'top';
            legend.innerText.split('\n').forEach((line, i) => { if (line.trim()) ctx.fillText(line, 8, 6 + i * 16); });
        }
        return canvas.toDataURL('image/png');
    }).then(image => fetch('/api/snapshot', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image, board_id: state.currentBoard, timeframe: state.currentTimeframe }),
    })).catch(e => console.warn('snapshot upload failed', e));
}

// ============ 视口程序化设置 ============
export function setVisibleTimeRange(fromSec, toSec) { setVisibleTimeRangeCore(fromSec, toSec); }

// ============ 铭牌/身份证卡/弹层（应用层零改） ============
export function openIdCard(boardId = null) {
    const bid = boardId || state.currentBoard;
    const lock = (state.locks || {})[bid] || {};
    const b = (state.boards || []).find(x => x.id === bid) || {};
    const body = document.getElementById('id-card-body');
    if (!body) return;
    const stem = String(lock.script || '').split('/').pop();
    const sym = (lock.identity || {}).symbol;
    body.innerHTML = `<h3>${sym ? `${stem}: ${sym}` : (stem || bid)} · 🔒 已锁定</h3>
<pre>${JSON.stringify({ identity: lock.identity || {}, script: lock.script,
    board: bid, intervals: b.intervals || [] }, null, 2)}</pre>
<p class="hint">${t('lock.hint')}</p>`;
    document.getElementById('id-card').style.display = 'flex';
}

export function bindOverlays() {
    const ic = document.getElementById('idcard-close');
    if (ic) ic.onclick = () => { document.getElementById('id-card').style.display = 'none'; };
    const ns = document.getElementById('idcard-new-scene');
    if (ns) ns.onclick = () => { document.getElementById('id-card').style.display = 'none'; openSearch(); };
    const ro = new ResizeObserver(() => resizeAllCharts());
    const host = document.querySelector('.chart-container');
    if (host) ro.observe(host);
    const ba = document.getElementById('board-add');
    if (ba) ba.onclick = () => openSearch();
    const gs = document.getElementById('guide-search-btn');
    if (gs) gs.onclick = () => openSearch();
    const es = document.getElementById('empty-search-btn');
    if (es) es.onclick = () => openSearch();
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') document.getElementById('id-card').style.display = 'none';
    });
}

// 最新价标签退役（Vela 原生 currentPriceLine 轴标签承担）；心跳 no-op 保 ws.js 零改
export function applyQuoteTick(_q) { /* 退役：原生轴标签 */ }
