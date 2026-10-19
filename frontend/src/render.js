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
import { openIndicatorLibrary } from './indicator_library.js';
import { effectiveStyle } from './visual_spec.js';   // V1：芯片色点与图上生效色同源
import {
    renderChartCore, applyDataUpdateCore, updateIndicatorSeriesCore,
    setVisibleTimeRangeCore, resizeAllChartsCore,
    onViewport, getVisibleTimeRange, onCrosshair, syncSubplotsCore, snapshotAll,
    tfMs, extendHistory, remountIndicator,
    refreshEmittedGroups, syncToolbarSticky,
} from './vela_adapter.js';

// ============ 活体注册表（resize 用；Vela 单图） ============
export function resizeAllCharts() { resizeAllChartsCore(); }

// ============ 应用层小工具 ============
function displayName(ind) { return (ind && ind.display_name) || (ind && ind.name) || ''; }

function updateDataInfo() {
    document.getElementById('data-info').textContent =
        `${(state.ohlcv || []).length} bars | ${Object.keys(state.indicators || {}).length} indicators`;
}

// 芯片色点 = 图上实际生效色（V1：与 effectiveStyle 同源，避免「芯片一个色、图上另一个色」）
//   多线取首线（bb=上轨、macd=DIF）；逐点色指标（sar）取首个语义槽（涨色）
function getIndicatorColor(ind) {
    const script = (ind && ind.script) || '';
    const lines = (ind && ind.lines) || [];
    if (lines.length) {
        const eff = effectiveStyle(script, lines[0].name, lines[0].style,
            ((ind.lines_style || {})[lines[0].name]), 0, lines[0].type);
        const ik = Object.keys(eff.inks || {});
        return (eff.hasInks && ik.length) ? eff.inks[ik[0]] : eff.color;
    }
    return effectiveStyle(script, null, ind && ind.style, ind && ind.style, 0).color;
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
    // P3：全指标单源 emit —— 隐藏=卸载该指标的 emit 组（视觉+图例行一起消失），显示=重新挂载。
    //   重挂载是必要的：emit 补丁只改模型，native 渲染器不重绘（V1 定论）。
    updateIndicatorSeries(name);
    remountIndicator(name);
    renderIndicatorBar();
    // P2-fix：显隐持久化到服务端真源（刷新恢复 + 多端一致）；广播回流幂等重应用。
    //   PUT 绑定约定=body 扁平（board_id/timeframe 也在 body，query 对 PUT 无效）。
    fetch(`/api/indicator/${encodeURIComponent(name)}`,
          { method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board_id: state.currentBoard, timeframe: state.currentTimeframe, visible: nowVisible }) })
        .catch(e => log('error', 'toggle persist: ' + (e && e.message)));
    log('info', t('ind.toggled', { name, st: nowVisible ? t('ind.shown') : t('ind.hidden') }));
}

function deleteIndicator(name) {
    const url = `/api/indicator/${encodeURIComponent(name)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`;
    fetch(url, { method: 'DELETE' })
        .then(r => r.json())
        .then(d => { if (d.error) log('error', t('ind.delete_fail', { e: d.error })); });
}

// 指标库面板（v0.5.3）：74 个 Vela 经典研究 + KDJ 扩展，搜索/分类/多列。
//   面板自己管增删；这里只提供「变更后刷新指标栏」回调（避免反向 import 环）。
function openIndicatorMenu() {
    openIndicatorLibrary(() => { renderIndicatorBar(); });
}

// ============ 渲染入口（rAF 节流 + 引导/空态分支 + 委托 adapter） ============
let renderScheduled = false;
export function renderChart() {
    if (renderScheduled) return;
    renderScheduled = true;
    requestAnimationFrame(() => { renderScheduled = false; _doRender(); });
    // OHLC 行预备填充（首载/重建后无十字线事件）：取最新一根
    [120, 500, 1200, 2500].forEach(ms => setTimeout(() => { try { _renderOhlcLatest(); } catch (e) {} }, ms));
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
        _setOhlcVisible(false);   // 无画板（删光/首次进入）= 引导页：OHLC 条带不该留在画布上方
        renderIndicatorBar(); updateDataInfo();
        return;
    }
    guide.style.display = 'none';
    if (!state.ohlcv || state.ohlcv.length === 0) {
        emptyState.style.display = 'block';
        container.innerHTML = '';
        _setOhlcVisible(false);   // 有板无数据（未加载/空窗）：同样不留旧读数
        renderIndicatorBar(); updateDataInfo();
        return;
    }
    emptyState.style.display = 'none';
    _setOhlcVisible(true);        // 有数据才显示（隐藏状态下切回画板即恢复）
    state.timeIndex = new Map(state.ohlcv.map((bar, i) => [Math.floor(bar.timestamp / 1000), i]));
    state.timeIndex = new Map(state.ohlcv.map((bar, i) => [Math.floor(bar.timestamp / 1000), i]));
    renderChartCore();                 // Vela 建图（adapter）
    renderSubplots();                  // 副图实例 diff + 动态总高（adapter；无 subplot DOM）
    renderIndicatorBar();
    updateDataInfo();
    reportView();
}

// ============ 增量更新 ============
export function applyDataUpdate() {
    applyDataUpdateCore();
    if (_ohlcHoverTime == null) _renderOhlcLatest();   // 未悬停时条带跟最新价走
    updateDataInfo();
    reportView();
}
// P1：prepend（左划回补广播）只同步缓存与视图上报，不动图表——Vela 经 loadRange 自取
export function applyPrependUpdate() {
    refreshEmittedGroups();   // P1 修复：prepend 后 vol/legacy 组 emit 与蜡烛对齐
    updateDataInfo();
    reportView();
}
export function updateIndicatorSeries(instId) { updateIndicatorSeriesCore(instId); }
export function renderSubplots() {
    // 单图表同图 pane 架构：无 subplot DOM div；实例 diff + 动态总高全在 adapter
    syncSubplotsCore();
}

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
// bug4：左划补历史 = 阈值触发（本回调）+ feed.loadRange 框架缝双通道（adapter 持有 backfill 单飞门）
onViewport(() => {
    const r = getVisibleTimeRange();
    // bug8：阈值周期感知（2 根 K 而非固定 2 天）——prepend 后旧左缘不再误判命中，断无限链
    const thr = 2 * tfMs(state.currentTimeframe);
    const hit = !!(state.ohlcv && state.ohlcv[0] && r && r.from <= state.ohlcv[0].timestamp + thr);
    if (!userTouched) return;
    if (!r || !state.ohlcv || !state.ohlcv.length) return;
    if (hit) extendHistory();   // P1：Vela 原生 extendDepth 单入口；单飞去重在 adapter loadRange
});

// ============ OHLC 读数行（Phase A-2） ============
// Vela 原生只把指标值画进 pane legend，OHLC 不在其中（dataWindowOHLC 仅进 aria/readout）
// → 该行自渲染，数据取官方十字线载荷（原始数值）/读数桥（格式化串），不自造数据。
export function refreshIndicatorBar() { renderIndicatorBar(); }
function _fmtOhlc(v) { return (v == null || !isFinite(v)) ? '--' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
// 条带显隐（无画板/无数据时隐藏；保留元素与绑定，回来即恢复，不重建）
function _setOhlcVisible(on) {
    const el = document.getElementById('ohlc-legend');
    if (el) el.style.display = on ? '' : 'none';
    syncToolbarSticky();   // 条带显隐会改 #main-chart 的 offsetTop（吸附基准）
}
function _ensureOhlcEl() {
    // 画布外条带（Vela 无 legend 位置配置，原生 legend 恒占画布内第一行）→ 本行置于图表上方=视觉第一行
    const container = document.querySelector('.chart-container');
    const host = document.getElementById('main-chart');
    if (!container || !host) return null;
    let el = document.getElementById('ohlc-legend');
    if (!el || !el.isConnected || el.parentElement !== container) {
        if (el && el.parentElement) el.parentElement.removeChild(el);
        el = document.createElement('div');
        el.id = 'ohlc-legend';
        container.insertBefore(el, host);
    }
    return el;
}
let _ohlcHoverTime = null;   // 十字线锁定的 bar 时间（ms）；null = 跟随最新
function _ohlcBarByTime(ms) {
    const bars = state.ohlcv || [];
    if (ms != null) {
        const i = bars.findIndex(b => b.timestamp === ms);
        if (i >= 0) return { bar: bars[i], prev: bars[i - 1] || null };
    }
    const i = bars.length - 1;
    return i >= 0 ? { bar: bars[i], prev: bars[i - 1] || null } : { bar: null, prev: null };
}
function _renderOhlcFromBar(bar, prev) {
    const el = _ensureOhlcEl();
    if (!el || !bar) return;
    const pct = prev && prev.close ? (bar.close - prev.close) / prev.close * 100
        : (bar.open ? (bar.close - bar.open) / bar.open * 100 : 0);
    const cls = pct >= 0 ? 'up' : 'down';
    const stamp = formatTimeCN(Math.floor((bar.timestamp || 0) / 1000), isIntraday(state.currentTimeframe));
    el.innerHTML =
        `<span class="ohlc-time">${stamp}</span>`
        + `<span>O <b>${_fmtOhlc(bar.open)}</b></span>`
        + `<span>H <b>${_fmtOhlc(bar.high)}</b></span>`
        + `<span>L <b>${_fmtOhlc(bar.low)}</b></span>`
        + `<span>C <b class="${cls}">${_fmtOhlc(bar.close)}</b></span>`
        + `<span class="${cls}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span>`;
}
function _renderOhlcLatest() {
    const { bar, prev } = _ohlcBarByTime(null);
    _renderOhlcFromBar(bar, prev);
}
(function bindOhlcRow() {
    onCrosshair((p) => {
        const o = p && p.ohlc;
        if (o && o.time != null) {
            _ohlcHoverTime = o.time;
            const hit = _ohlcBarByTime(o.time);
            _renderOhlcFromBar(hit.bar || { ...o, timestamp: o.time }, hit.prev);
            return;
        }
        _ohlcHoverTime = null;          // 移出画布：回落到最新一根
        _renderOhlcLatest();
    });
})();

// ============ 图例 ============
// Phase A（Vela 原生体验）：图例全部交给 Vela 原生 pane legend（价格/成交量/副图统一，
// 十字线天然跟随）。自绘 DOM 图例体系（含时区敏感反查桥）与原生 legend 冲突 → 整体移除。
// ============ 截图（snapshot_request） ============
export function captureSnapshot() {
    const shots = snapshotAll();
    if (!shots.length) return;
    Promise.all(shots.map(sh => fetch(sh.url).then(r => r.blob()).then(bl => createImageBitmap(bl)).then(bmp => ({ key: sh.key, bmp })))).then(items => {
        const W = Math.max(...items.map(it => it.bmp.width));
        const H = items.reduce((a, it) => a + it.bmp.height, 0);
        const canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#131722'; ctx.fillRect(0, 0, W, H);
        let y = 0;
        items.forEach(it => {
            ctx.drawImage(it.bmp, 0, y);
            y += it.bmp.height;
        });
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
