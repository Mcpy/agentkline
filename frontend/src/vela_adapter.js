// ============================================================================
// vela_adapter.js —— Vela 唯一接触点（v0.5 R2 薄适配层纪律）
// 应用层不得直接摸 window.Vela，全经本文件。
// 兼容基线契约 = docs/v0.5-需求与改动点.md §2 映射表（PoC 0.8.1 验过的 API 面）。
//
// v0.5.0 图表架构（用户裁决 2026-10-03 三轮定案）：单图表同图 pane + 动态总高。
//   产品承诺（2026-09-27）：主图固定高不随副图压缩、超出 wheel 翻。
//   实现（P3 单路径）：pane 高=官方 heightWeight 旋钮（0.4 像素目标作相对权重，零像素校准），
//   容器总高=Σ目标（超出 wheel 翻）；加/删副图 → _layoutPanes() 单路径重算。
//   同图收益：视口/十字线/截图/成交量全免费（无多图表同步层、无透明假 bar）。
// 注意事项锚点：§10-①..⑭ + 附二（深拷贝/事件缺/双格式读/slice(8)/ctx.id 等）。
// ============================================================================
import { state } from './state.js';

const V = window.Vela;

// ---- 常量与工具 ----
const MAIN_H = 450;          // 主图固定像素高（0.4 产品承诺）
const VOL_H = 110;           // 成交量常驻窗格
const VOL_UP = 'rgba(38,166,154,0.6)';    // 0.4 成交量涨跌色（P2 起经原生 volume 输入项配置）
const VOL_DOWN = 'rgba(239,83,80,0.6)';
const ms = (bar) => bar.timestamp;                       // state.ohlcv.timestamp 已是 ms
const LS = (n) => (n === 1 ? 'dotted' : n === 2 ? 'dashed' : 'solid');   // LWC 0/1/2 → Vela
const clone = (o) => JSON.parse(JSON.stringify(o));       // §10-⑤ 活引用硬约定

import { NATIVE_MAP, nativeMulti, nativeTypeOf, styleInputs, lineStyleInputs, lineColorKey } from './native_map.js';

// ---- dataFeed（R3）：后端 WS 数据 → Vela MarketDataFeed port；零 provider 注册 ----
class AkFeed {
    constructor() { this._onBar = null; }
    async load() {
        return (state.ohlcv || []).map(b => ({ time: ms(b), open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }));
    }
    // Vela 原生历史通道（P1 原生化）：loadRange = 历史唯一入口，后端 store 为唯一真源。
    // 契约（bundle 考古 backfillHistory）：{to, limit, from?} → 严格 time<to、ascending、≤limit；空数组 = genesis。
    // 镜像（state.ohlcv）降格为应用缓存：只同步写、不参与命中/到底判定；客户端零闩锁：
    // 到底 = 服务端 backfill prepended=0；按图实例的 genesis 闩锁由 Vela 原生持有（切板/重建即重置）。
    async loadRange(cfg, range) {
        const to = (range && range.to != null) ? range.to : Infinity;
        const from = (range && range.from != null) ? range.from : null;
        const limit = (range && range.limit != null) ? range.limit : 200;
        const mapb = b => ({ time: ms(b), open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume });
        if (to === Infinity) return (state.ohlcv || []).map(mapb);   // 防御：框架全窗语义
        let chunk;
        if (from != null) {
            // 中段缺口修复（healGap 语义）：只窗取不 backfill
            chunk = (await fetchWindow(from, to - 1) || []).filter(b => ms(b) >= from);
        } else {
            const key = String(to);
            if (!_headFlights.has(key)) {
                _headFlights.set(key, fetchHeadChunk(to, limit).finally(() => { _headFlights.delete(key); }));
            }
            chunk = (await _headFlights.get(key)) || [];
        }
        const out = (chunk || []).filter(b => ms(b) < to).sort((a, b) => a.timestamp - b.timestamp);
        return (limit != null ? out.slice(-limit) : out).map(mapb);
    }
    subscribe(cfg, onBar) { this._onBar = onBar; return () => { this._onBar = null; }; }
    destroy() { this._onBar = null; }
    _push(bar) { if (this._onBar) this._onBar({ time: ms(bar), open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume }); }
}
const feed = new AkFeed();

// ============================================================================
// native indicator 组通道（PoC P1 路径 A，官方 emit port）：legacy 脚本值直喂。
//   'ak-main' = overlay group; 'ak-sub::<name>' = per-subplot group。
//   P2：成交量已交原生 volume 指标（store 驱动），不再经本通道。
//   type name = group name (ctx.id=native-N unreliable, §10-9); multiInstance guards re-add.
// ============================================================================
const _emitGroups = {};        // groupKey#ctxId → ctx
function _groupSeries(groupId) {
    const series = [];
    const pushInd = (ind, instId) => {
        if (nativeTypeOf(ind.script)) return;   // Phase A：原生指标由内置通道绘制，旧 emit 不重复发
        const vis = state.visibility[instId] !== false;
        const lines = (ind.lines && ind.lines.length) ? ind.lines : null;
        let count = 0;
        if (lines) {
            const rank = (l) => (l.type === 'histogram' || l.type === 'bar') ? 0 : 1;
            [...lines].sort((a, b) => rank(a) - rank(b)).forEach((line, idx) => {
                series.push(_lineSpec(`${instId}_${idx}`, line.name || `${instId}_${idx}`, line.values, line.type, line.style, vis));
                count++;
            });
        } else {
            series.push(_lineSpec(instId, ind.display_name || ind.name || instId, ind.values, ind.type, ind.style, vis));
            count = 1;
        }
        _emitLines[instId] = count;   // P2：emit 注册表（取代 seriesMap 占位）
    };
    Object.entries(state.indicators || {}).forEach(([instId, ind]) => {
        const wantSub = groupId === 'ak-main' ? !ind.subplot : (ind.subplot === groupId.slice(8));   // 'ak-sub::'.length=8（bug2 off-by-one 修）
        if (wantSub) pushInd(ind, instId);
    });
    return series;
}
function _lineSpec(id, title, values, type, style, vis) {
    style = style || {};
    const kind = (type === 'histogram' || type === 'bar') ? 'histogram' : type === 'area' ? 'area' : 'line';   // baseline 降级 line（§10-⑭）
    const color = style.color || '#4fc3f7';
    // 索引对齐（P2 定性）：后端 values 与服务端 store 索引对齐；P1 不变量「镜像 ≡ 服务端 store」
    // 使 off = bars.len - values.len 为精确对齐而非启发式；瞬态广播乱序时由 null 点自然降级。
    const bars = state.ohlcv || [];
    const off = Math.max(0, bars.length - (values || []).length);
    const points = (values || []).map((v, i) => {
        const bar = bars[off + i];
        const pt = { time: bar ? ms(bar) : i, value: (v == null ? null : v) };
        if (kind === 'histogram' && v != null && style.autoColor !== false) pt.color = v >= 0 ? '#26a69a' : '#ef5350';
        return pt;
    });
    return { id, title, paneId: '', kind, points, visible: vis,
             style: { color, width: style.lineWidth || 2, lineStyle: LS(style.lineStyle) } };
}
const _registeredTypes = new Set();
function _ensureType(type, title, paneHint, overlay, legend) {
    if (_registeredTypes.has(type)) return;
    _registeredTypes.add(type);
    V.registerNativeIndicator({
        type, title, paneHint, overlay, legend, multiInstance: true,
        inputsSchema: () => [], defaultInputs: () => ({}),
        create: () => ({
            start(ctx) { _emitGroups[type + '#' + ctx.id] = ctx; ctx.emit({ series: _groupSeries(type) }); ctx.setStatus('live'); },
            onBars() {}, setInputs() {}, suspend() {}, resume() {},
            stop() { Object.keys(_emitGroups).forEach(k => { if (k.startsWith(type + '#')) delete _emitGroups[k]; }); },
        }),
    });
}
function reEmit(groupId) {
    Object.entries(_emitGroups).forEach(([k, ctx]) => { if (k.startsWith(groupId + '#')) ctx.emit({ series: _groupSeries(groupId) }); });
}
// P2：legacy 组（ak-main + ak-sub::*）重发；成交量已交原生 volume，不再经 emit
function reEmitLegacyGroups() { ['ak-main', ...Object.keys(state.subplots || {}).map(n => 'ak-sub::' + n)].forEach(reEmit); }
export function refreshEmittedGroups() { reEmitLegacyGroups(); }
let _emitLines = {};   // instId -> 已 emit 线数（结构变化判定，取代 state.seriesMap）
export function legacySeriesCount(instId) { return _emitLines[instId] || 0; }

// ============================================================================
// 单图表活体 + 动态总高 relayout（产品承诺实现）
// ============================================================================
let chart = null;
let _chartReady = false;

function _destroyChart() {
    if (chart) { try { chart.destroy(); } catch (e) {} }
    chart = null;
    _chartReady = false;
    _volMoved = false;
    Object.keys(_emitGroups).forEach(k => delete _emitGroups[k]);
}
// ============================================================================
// P3 单布局路径：pane 顺序/归属由 Vela 管理；高度走官方 heightWeight 旋钮，
// 0.4 像素目标作相对权重（price=450/vol=110/sub=sp.height||150，零像素校准常数）；
// 容器总高 = Σ 权重（= Σ 目标像素，超出由 .chart-container wheel 翻 = 0.4 滚动承诺）；
// volume 常驻顶位（0.4 语义）。删除：OVERHEAD 校准 / _relayoutPanes legacy 分支 / 双路径。
// ============================================================================
const _isVolPane = p => (p.indicators || []).some(i => i.nativeType === 'volume' || (i.nativeType || i.title) === 'ak-vol' || i.title === 'Volume');
function _paneWeight(p) {
    if (p.id === 'price') return MAIN_H;
    if (_isVolPane(p)) return VOL_H;
    const t = ((p.indicators || []).map(i => i.nativeType || '').find(n => n.startsWith('ak-sub::'))) || '';
    const sp = t ? (state.subplots || {})[t.slice(8)] : null;
    return (sp && sp.height) || 150;
}
let _layoutRaf = 0;
let _volMoved = false;   // 每图一次：volume 移入独立 pane
function _layoutPanes() {
    if (_layoutRaf) return;
    _layoutRaf = requestAnimationFrame(() => { _layoutRaf = 0; _layoutPanesNow(); });
}
function _layoutPanesNow() {
    if (!chart) return;
    // P3：原生 volume 默认 overlay 在 price pane（0.8.4 paneHint:'price'）；裁决=独立顶位 pane。
    // 自动挂载时机可能晚于 ready → 在布局路径补捉 moveTo({newPane:true})（官方入口，每图一次）。
    if (!_volMoved) {
        const vh = (chart.indicators() || []).find(h => h.nativeType === 'volume');
        if (vh && vh.moveTo) {
            try { vh.moveTo({ newPane: true }); _volMoved = true; } catch (e) { console.warn('[ak] volume moveTo newPane failed:', e && e.message); }
        }
    }
    let pl = chart.panes.list() || [];
    const volPane = pl.find(_isVolPane);
    if (volPane) {
        let g = 0;
        while ((chart.panes.list() || []).findIndex(p => p.id === volPane.id) > 1 && g++ < 8) {
            try { chart.panes.move(volPane.id, 'up'); } catch (e) { break; }
        }
    }
    pl = chart.panes.list() || [];
    pl.forEach(p => { try { p.heightWeight = _paneWeight(p); } catch (e) {} });
    const total = pl.reduce((a, p) => a + _paneWeight(p), 0);
    const el = document.getElementById('main-chart');
    const target = total + 'px';
    const changed = el && el.style.height !== target;
    if (changed) el.style.height = target;   // 仅变化时写：防 ResizeObserver→resize 环（闪烁根因之一）
    if (changed) { try { chart.resize(); } catch (e) {} }
}
let _lastPaneCount = -1;
function _afterNativeChange() {
    _layoutPanes();
    const n = (() => { try { return (chart.panes.list() || []).length; } catch (e) { return -1; } })();
    if (n === _lastPaneCount) return;          // pane 数未变（叠加类指标）→ 不整图重绘
    _lastPaneCount = n;
    setTimeout(() => { if (chart) { try { chart.resize(); } catch (e) {} } }, 40);
}
export function renderChartCore() {
    _nativeInd.clear(); _pendingNative.clear();   // Phase A：整图重建 → 旧原生句柄全部失效
    _emitLines = {};                               // P2：emit 注册表随重建清空
    const hasLegacyOverlay = Object.values(state.indicators || {}).some(i => !nativeTypeOf(i.script) && !i.subplot);
    if (hasLegacyOverlay) _ensureType('ak-main', 'Indicators (overlay)', 'price', true, false);
    _destroyChart();
    const container = document.getElementById('main-chart');
    if (!container) return;
    container.innerHTML = '';
    chart = new V.Vela(container, {
        symbol: chartSymbol(),
        timeframe: state.currentTimeframe || '1d',
        theme: 'dark', live: true, volume: true,   // P2：成交量交原生 volume 指标（独立 pane，store 驱动恒对齐）
        currentPriceLine: true,            // 原生最新价轴标签（替代 0.4 自绘吸附标签）
        drawings: { toolbar: false },      // 画线工具入口=侧栏桥接（C3）
    }, { dataFeed: feed });
    try { chart.renderer.set('attribution', false); } catch (e) {}   // 归因甲案（R6-2）
    chart.on('viewport:changed', () => _viewportCbs.forEach(cb => cb()));
    chart.on('history:complete', () => { _backfillActive = false; clearTimeout(_backfillActiveT); });
    chart.on('history:progress', () => _markBackfillActive());
    _bindCrosshairBridge(chart);
    chart.ready().then(() => {
        if (!chart) return;
        _chartReady = true;
        if (Object.values(state.indicators || {}).some(i => !nativeTypeOf(i.script) && !i.subplot)) {
            try { chart.addNativeIndicator('ak-main'); } catch (e) {}
        }
        // P2/P3：原生 volume 由构造选项自动挂载（默认 overlay 在 price pane，0.8.4 paneHint:'price'）；
        // 裁决=独立顶位 pane → moveTo({newPane:true}) 官方入口移入自有 pane，再配 0.4 涨跌色。
        try {
            const vh = (chart.indicators() || []).find(h => h.nativeType === 'volume');
            if (vh && vh.setInputs) vh.setInputs({ upColor: VOL_UP, downColor: VOL_DOWN });
        } catch (e) {}
        syncNativeIndicators().then(() => { _layoutPanes(); });   // 首载/重建后同步原生指标并布局（P3 单路径）
        syncSubplotsCore();       // 内部含 _layoutPanes
        setTimeout(() => _layoutPanes(), 400);   // 补捉晚于 ready 的 volume 自动挂载
        _showLatest(200);
        syncDrawings();
        syncMarks();
        bindDrawingWriteback();
    });
}
// 副图实例 diff 同步（bug2-b：subplot_add/remove 消息序无关）+ relayout
export function syncSubplotsCore() {
    if (!chart || !_chartReady) return;    // pre-ready adds are dropped by the framework (evidence: panes=1); defer to ready.then
    // live truth = chart.indicators()（同步可靠；自有注册表异步写不可靠）
    const live = (chart.indicators() || []).map(h => h.nativeType).filter(t => t && t.startsWith('ak-sub::'));
    // Phase A：原生指标自带 pane（overlay:false 的内置振荡器），其 subplot 名不再建旧 pane
    const nativeOwned = new Set(Object.values(state.indicators || {})
        .filter(i => nativeTypeOf(i.script) && i.subplot).map(i => i.subplot));
    const want = Object.keys(state.subplots || {}).filter(n => !nativeOwned.has(n)).map(n => 'ak-sub::' + n);
    want.forEach(type => {
        if (!live.includes(type)) {
            const name = type.slice(8);
            _ensureType(type, name, 'new', false, true);    // subplot native legend lives in its own pane (bug3 fix)
            try { chart.addNativeIndicator(type); } catch (e) {}
        }
    });
    live.forEach(type => {
        if (!want.includes(type)) {
            try {
                (chart.indicators() || []).filter(h => h.nativeType === type).forEach(h => h.remove && h.remove());
            } catch (e) {}
            Object.keys(_emitGroups).forEach(k => { if (k.startsWith(type + '#')) delete _emitGroups[k]; });
        }
    });
    _layoutPanes();
}

function _showLatest(n) {
    const bars = state.ohlcv || [];
    if (!chart || !bars.length) return;
    const from = bars[Math.max(0, bars.length - n)].timestamp;
    const to = bars[bars.length - 1].timestamp + 2 * _tfMs(state.currentTimeframe);
    try { chart.setVisibleRange({ from, to }); } catch (e) {}
}
export function tfMs(tf) { return _tfMs(tf); }
function _tfMs(tf) {
    const m = { '1m': 60e3, '5m': 300e3, '15m': 900e3, '30m': 1800e3, '1h': 3600e3, '4h': 14400e3, '1d': 86400e3, '1w': 604800e3 };
    return m[tf] || 86400e3;
}
function chartSymbol() { return (state.currentBoard || 'AK') + ':' + (state.currentTimeframe || '1d'); }

// ---- 实时/增量（ws.js tick 语义；P1：prepend 不再走这里，Vela 经 loadRange 自取） ----
export function applyDataUpdateCore() {
    if (!chart) { renderChartCore(); return; }
    const bars = state.ohlcv || [];
    if (!bars.length) return;
    feed._push(bars[bars.length - 1]);
    reEmitLegacyGroups();   // tick 使 legacy 序列末点位移（镜像≡store 不变量下的精确索引对齐）
}
// ============================================================================
// 原生指标管理（重构 Phase A）：add/remove/update 走 Vela 内置指标句柄，
// 零整图重建、零 WS 值推送、零自定义 emit。未映射脚本返回 false → 旧通道回退。
// ============================================================================
// 样式真源派生：常规广播把样式嵌在 lines[].style（style 字段为 null）→ 统一成 dict
function _linesStyleOf(inst) {
    // 优先级：lines[].style（弹窗显示/用户调好的真源） > lines_style（可能残留旧值）
    if (!inst) return null;
    const out = {};
    if (inst.lines_style) Object.assign(out, inst.lines_style);
    (inst.lines || []).forEach(l => { if (l && l.style && l.name) out[l.name] = { ...(out[l.name] || {}), ...l.style }; });
    return Object.keys(out).length ? out : null;
}
function _styleOf(inst) {
    if (!inst) return null;
    if (inst.style) return inst.style;
    const ls = inst.lines || [];
    if (ls.length === 1 && ls[0].style) return ls[0].style;
    return null;
}
const _nativeInd = new Map();   // ourInstId -> {handle?, handles?, script}
const _pendingNative = new Set();   // pre-ready 到达的原生指标（ready 后由 syncNativeIndicators 补挂）

export async function addIndicatorNative(inst) {
    if (!chart || !inst || !inst.script) return false;
    const map = NATIVE_MAP[inst.script];
    const multi = nativeMulti(inst.script);
    if (!map && !multi) return false;                        // 未映射 → 旧通道回退
    if (_nativeInd.has(inst.inst_id)) return true;   // 幂等：防重复实例（双 pane）
    if (!_chartReady) { _pendingNative.add(inst.inst_id); return true; }   // pre-ready：认领挂起，ready 后补挂
    // Vela addNativeIndicator = 同步返回 handle（非 Promise；对 .then 会抛错=此前实例累积/单线根因）
    try {
        if (map) {
            const h = chart.addNativeIndicator(map.type, { id: inst.inst_id, title: inst.display_name });
            const ls0 = _linesStyleOf(inst), st0 = _styleOf(inst);
            const in0 = { ...map.inputs(inst.params || {}), ...lineStyleInputs(inst.script, ls0),
                ...styleInputs(inst.script, st0, ls0) };   // 显式 style 最后胜出（含 lines[].style 派生）
            if (h && h.setInputs) h.setInputs(in0);
            _nativeInd.set(inst.inst_id, { handle: h, script: inst.script, lastInputs: JSON.stringify(in0) });
            _afterNativeChange();
            return true;
        }
        if (multi) {
            const periods = ((inst.params || {}).periods || [20]).slice();
            const ids = [];
            periods.forEach(per => {
                const id = periods.length > 1 ? `${inst.inst_id}_${per}` : inst.inst_id;
                const h = chart.addNativeIndicator(multi, { id });
                if (h && h.setInputs) h.setInputs({ length: per });
                _nativeInd.set(id, { handle: h, script: inst.script });
                ids.push(id);
            });
            _nativeInd.set(inst.inst_id, { handles: ids, script: inst.script, lastPeriods: periods, multiSig: periods.join(',') });
            _afterNativeChange();
            return true;
        }
    } catch (e) { console.warn('[ak] addNativeIndicator failed:', inst.script, e && e.message); }
    return false;
}

export function removeIndicatorNative(instId) {
    const rec = _nativeInd.get(instId);
    if (!rec) return false;
    if (rec.handles) rec.handles.forEach(id => { const r = _nativeInd.get(id); if (r && r.handle) { try { r.handle.remove(); } catch (e) {} _nativeInd.delete(id); } });
    else if (rec.handle) { try { rec.handle.remove(); } catch (e) {} }
    _nativeInd.delete(instId);
    _afterNativeChange();
    return true;
}

export function updateIndicatorNative(instId, params, style, linesStyle) {
    const rec = _nativeInd.get(instId);
    if (!rec) return false;
    const cur = (state.indicators || {})[instId] || {};
    // 用户裁决：自家 state 是样式真源 → state 派生优先于广播携带（广播可能残留旧值，曾把颜色顶回默认）
    const dSt = _styleOf(cur), dLs = _linesStyleOf(cur);
    if (dLs) linesStyle = dLs;
    if (dSt) style = dSt;
    const map = NATIVE_MAP[rec.script];
    if (map && rec.handle) {
        const next = { ...map.inputs(params || {}), ...lineStyleInputs(rec.script, linesStyle),
            ...styleInputs(rec.script, style, linesStyle) };   // 显式 style 最后胜出（广播里的 lines_style 不再顶掉）
        const sig = JSON.stringify(next);
        if (rec.lastInputs === sig) return true;          // 广播逐 tick 重复 → 参数未变=零重算零重绘（防闪）
        rec.lastInputs = sig;
        try { rec.handle.setInputs(next); } catch (e) {}
        return true;
    }
    if (rec.handles || nativeMulti(rec.script)) {         // 多实例（sma/ema）：收敛式同步（不依赖广播内容）
        const styleSig = JSON.stringify([style || null, linesStyle || null]);
        const applyStyles = () => {
            const idsNow = [..._nativeInd.keys()].filter(k => { const r = _nativeInd.get(k); return r && r.script === rec.script && !r.handles; });
            idsNow.forEach(id => {
                const r = _nativeInd.get(id); if (!r || !r.handle || !r.handle.setInputs) return;
                const per = r.handle.inputValues ? (r.handle.inputValues().length ?? null) : null;
                const inp = {};
                const lineName = linesStyle ? Object.keys(linesStyle).find(n => String(n).replace(/\D/g, '') === String(per)) : null;
                const ls = lineName && linesStyle[lineName];
                if (ls && ls.color) inp.color = ls.color;
                else if (style && style.color) inp.color = style.color;
                if (Object.keys(inp).length) { try { r.handle.setInputs(inp); } catch (e) {} }
            });
            rec.multiStyleSig = styleSig;
        };
        const multi = nativeMulti(rec.script);
        const p = (params || {});
        const want = (Array.isArray(p.periods) && p.periods.length) ? p.periods.map(Number)
            : (rec.lastPeriods || []).length ? rec.lastPeriods : [20];
        const sig = want.join(',');
        if (rec.multiSig === sig && rec.multiStyleSig === styleSig) return true;   // 周期与样式都未变 = 纯 no-op
        if (rec.multiSig === sig) { applyStyles(); return true; }                  // 仅样式变化
        rec.multiSig = sig; rec.lastPeriods = want;
        // 现有实例（我们自己的 key 规则：instId 或 instId_per）
        const existing = [..._nativeInd.entries()].filter(([k, v]) => v.script === rec.script && !v.handles);
        const wantIds = new Set(want.map(per => want.length > 1 ? `${instId}_${per}` : instId));
        // 删多余
        existing.forEach(([k]) => { if (!wantIds.has(k)) { const r = _nativeInd.get(k); if (r && r.handle) { try { r.handle.remove(); } catch (e) {} } _nativeInd.delete(k); } });
        // 补缺失（同帧并发）
        const have = new Set(existing.map(([k]) => k));
        want.filter(per => !have.has(want.length > 1 ? `${instId}_${per}` : instId)).forEach(per => {
            const id = want.length > 1 ? `${instId}_${per}` : instId;
            try { const h = chart.addNativeIndicator(multi, { id }); if (h && h.setInputs) h.setInputs({ length: per }); _nativeInd.set(id, { handle: h, script: rec.script }); } catch (e) {}
        });
        rec.handles = [...wantIds];
        applyStyles();
        _afterNativeChange();
        return true;
    }
    return false;
}

export function hasNativeIndicator(instId) { return _nativeInd.has(instId); }
// 弹窗初值：读原生句柄真值（单实例=输入表；多实例=按周期分组）
export function nativeInputValues(instId) {
    const rec = _nativeInd.get(instId);
    if (!rec) return null;
    if (rec.handle && rec.handle.inputValues) { try { return { single: rec.handle.inputValues() }; } catch (e) { return null; } }
    if (rec.handles) {
        const byPeriod = {};
        rec.handles.forEach(id => { const r = _nativeInd.get(id); if (r && r.handle && r.handle.inputValues) {
            const v = r.handle.inputValues(); byPeriod[v.length] = v; } });
        return { byPeriod };
    }
    return null;
}
export function lineColorKeyOf(script, lineName) { return lineColorKey(script, lineName); }
export function pricePaneIndicatorRows() {
    try {
        const pl = chart.panes.list() || [];
        const price = pl.find(p => p.id === 'price');
        const n = price ? (price.indicators || []).length : 0;
        return Math.max(1, n);   // 原生 legend 占行数（含首行）
    } catch (e) { return 1; }
}
export function setIndicatorVisibleNative(instId, visible) {
    const rec = _nativeInd.get(instId);
    if (!rec) return false;
    const list = rec.handles ? rec.handles.map(id => _nativeInd.get(id)).filter(Boolean) : [rec];
    list.forEach(r => { if (r && r.handle && r.handle.setVisible) { try { r.handle.setVisible(!!visible); } catch (e) {} } });
    return true;
}
export async function syncNativeIndicators() {
    const inds = state.indicators || {};
    for (const [id, ind] of Object.entries(inds)) {
        if (_nativeInd.has(id)) continue;
        await addIndicatorNative({ ...ind, inst_id: id });
        if (state.visibility && state.visibility[id] === false) setIndicatorVisibleNative(id, false);
    }
    _pendingNative.clear();
}
export function nativeIndicatorIds() { return [..._nativeInd.keys()]; }

window.__akInputs = () => (chart.indicators() || []).map(h => {
    let keys = [];
    try { keys = Object.keys(h.inputValues ? h.inputValues() : {}); } catch (e) {}
    return { type: h.nativeType, keys };
});
// 调试钩子（排障用，勿用于业务）：左滑触发/视口/镜像头/在途取数/pane 布局真值
window.__akDebug = {
    extend: () => extendHistoryCore(),
    vr: () => getVisibleTimeRange(),
    head: () => (state.ohlcv || [])[0] ? (state.ohlcv || [])[0].timestamp : null,
    inflight: () => _headFlights.size,
    panes: () => ((chart && chart.panes.list()) || []).map(p => ({ id: p.id, w: p.heightWeight, types: (p.indicators || []).map(i => i.nativeType || i.title) })),
    subs: () => Object.keys(state.subplots || {}),
    inds: () => Object.entries(state.indicators || {}).map(([id, i]) => [id, i.script, i.subplot || null]),
};
// P1：左划提深度 = Vela 原生 extendDepth 单入口（setMarket 同 market + bars）。
// 目标深度 = 镜像长度 + 200。不变量：镜像 ⊇ Vela BarStore（初载快照同源 + 增量同源），
// 故 target 恒 > rawBars → extendDepth 必走 backfill 分支而非头部 slice 分支。
// 零冷却/零指针门/零 genesis 缓存：in-flight 去重由 loadRange 单飞承担，
// 到底由服务端 prepended=0 → 空 chunk → Vela 按实例 genesis 闩锁（切板/重建重置）。
export function extendHistory() { extendHistoryCore(); }
let _backfillActive = false;   // 事件驱动 in-flight 标记：history:complete 清除（兜底超时防事件丢）
let _backfillActiveT = 0;
function _markBackfillActive() {
    _backfillActive = true;
    clearTimeout(_backfillActiveT);
    _backfillActiveT = setTimeout(() => { _backfillActive = false; }, 3000);
}
function extendHistoryCore() {
    if (!chart) return;
    // in-flight 门：backfill 在途时跳过新触发——Vela 自有循环会追平目标深度，
    // 拖拽期间的二次 setMarket 曾与 in-flight 合并碰撞致渲染头卡死（视口 pan 不进新区→hit 恒假）。
    if (_backfillActive || _headFlights.size) return;
    const bars = state.ohlcv || [];
    if (!bars.length) return;
    const n = bars.length + 200;
    _markBackfillActive();
    try {
        chart.setMarket({ symbol: chartSymbol(), timeframe: state.currentTimeframe || '1d', bars: n })
            .catch(e => console.warn('[ak] depth extend failed', e));
    } catch (e) { console.warn('[ak] setMarket(bars) depth extend failed', e); }
}
export function updateIndicatorSeriesCore(instId) {
    const ind = (state.indicators || {})[instId];
    if (!ind) return;
    const want = (ind.lines && ind.lines.length) ? ind.lines.length : (ind.values ? 1 : 0);
    if (legacySeriesCount(instId) !== want) { renderChartCore(); return; }   // 结构变化=全量（P2：emit 注册表判定）
    reEmit(ind.subplot ? 'ak-sub::' + ind.subplot : 'ak-main');
}

// ---- 重构 A+B：provider 式自足 loadRange + 去重/单调守卫合并（借鉴 Vela v2/backfillHistory 校验） ----
function mergeIntoMirror(chunk) {
    const cur = state.ohlcv || [];
    const m = new Map();
    for (const b of cur) m.set(b.timestamp, b);
    const sorted = (chunk || []).slice().sort((a, b) => a.timestamp - b.timestamp);
    let prev = -Infinity, mono = true;
    for (const b of sorted) { if (b.timestamp <= prev) mono = false; prev = b.timestamp; m.set(b.timestamp, b); }
    if (!mono) console.warn('[ak] non-monotonic head chunk — deduped by time (Vela-style guard)');
    state.ohlcv = [...m.values()].sort((a, b) => a.timestamp - b.timestamp);
    state.timeIndex = new Map(state.ohlcv.map((bar, i) => [Math.floor(bar.timestamp / 1000), i]));
}
const _headFlights = new Map();   // 单飞：同 to 的并发 loadRange 共享同一次头部取数
// 头部取数（P1 修复）：计数型 until 窗口（服务端按根数切片，与日历无关 ⇒ 镜像头与 Vela 头恒对齐，
// 交易日缺口源不再因日历窗欠覆盖而两头漂移）。先窗取（store 可能已有更旧 bar，如上次 backfill 残留），
// 窗空才 POST backfill；backfill 后窗仍空 = 服务端确认无更旧 = genesis（不缓存，Vela 按实例闩锁）。
async function fetchHeadChunk(to, limit) {
    const b = state.currentBoard, tf = state.currentTimeframe;
    if (!b || !tf) return [];
    const n = (limit || 200) + 2;
    const chunk = await fetchUntilWindow(to, n);
    if (chunk.length) return chunk;
    try {
        const r = await fetch(`/api/board/${encodeURIComponent(b)}/timeframe/${encodeURIComponent(tf)}/backfill`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: limit || 200 }) });
        const bj = await r.json().catch(() => null);
        const prep = bj && (bj.prepended != null ? bj.prepended : bj.added);
        if (!prep) return [];
        return await fetchUntilWindow(to, n);
    } catch (e) { return []; }
}
async function fetchUntilWindow(to, n) {
    const b = state.currentBoard, tf = state.currentTimeframe;
    if (!b || !tf) return [];
    try {
        const g = await fetch(`/api/kline?board_id=${encodeURIComponent(b)}&timeframe=${encodeURIComponent(tf)}&until=${to}&limit=${n}`);
        if (!g.ok) return [];
        const gj = await g.json().catch(() => null);
        const chunk = (gj && gj.ohlcv) || [];
        if (chunk.length) mergeIntoMirror(chunk);   // 镜像=缓存：同步写仅供应用层，不参与历史判定
        return chunk;
    } catch (e) { return []; }
}
// 窗口取数（start/end 时间窗）：仅 healGap 中段修复使用
async function fetchWindow(start, end) {
    const b = state.currentBoard, tf = state.currentTimeframe;
    if (!b || !tf) return [];
    try {
        const g = await fetch(`/api/kline?board_id=${encodeURIComponent(b)}&timeframe=${encodeURIComponent(tf)}&start=${start}&end=${end}`);
        if (!g.ok) return [];
        const gj = await g.json().catch(() => null);
        const chunk = (gj && gj.ohlcv) || [];
        if (chunk.length) mergeIntoMirror(chunk);   // 镜像=缓存：同步写仅供应用层（reportView/legacy emit），不参与历史判定
        return chunk;
    } catch (e) { return []; }
}

// ---- 视口 ----
const _viewportCbs = [];
export function onViewport(cb) { _viewportCbs.push(cb); }
export function getVisibleTimeRange() {
    if (!chart) return null;
    const r = chart.getVisibleRange();
    return r ? { from: r.from, to: r.to } : null;
}
export function setVisibleTimeRangeCore(fromSec, toSec) {
    if (!chart || !(toSec > fromSec)) return;
    chart.setVisibleRange({ from: fromSec * 1000, to: toSec * 1000 });   // 秒→ms（§2 锚点）
}
export function resizeAllChartsCore() { if (chart) { try { chart.resize(); } catch (e) {} } }

// ---- 截图（单 canvas 含全 pane；renderer.screenshot 返回 dataURL，p8 已验） ----
export function snapshotAll() {
    if (!chart) return [];
    try { return [{ key: 'main', url: chart.renderer.screenshot() }]; } catch (e) { return []; }
}

// ---- 十字线官方通道（bug6）：onCrosshairMove 载荷含 hovered bar 原始 ms 时间，
//      全 pane 统一触发；取代旧 mousemove+date 字符串反查（时区敏感，UTC+8 必失配） ----
const _crosshairSubs = new Set();
export function onCrosshair(cb) { _crosshairSubs.add(cb); return () => _crosshairSubs.delete(cb); }
function _bindCrosshairBridge(ch) {
    // p13 内省：facade(chart) 无 onCrosshairMove；入口在能力代理层 chart.renderer（Pi），
    // 其转发到持有 crosshairCbs 的场景控制器（Ys）。逐层回退订阅。
    const target = (ch && ch.renderer && typeof ch.renderer.onCrosshairMove === 'function') ? ch.renderer
        : (ch && typeof ch.onCrosshairMove === 'function') ? ch : null;
    if (!target) { console.warn('[ak] crosshair bridge: no onCrosshairMove entry'); return; }
    try {
        target.onCrosshairMove((p) => { _crosshairSubs.forEach(fn => { try { fn(p); } catch (e) {} }); });
    } catch (e) { console.warn('[ak] onCrosshairMove unavailable', e); }
}
export function readDataWindow() {
    if (!chart || !chart.renderer || !chart.renderer.dataWindowReadout) return null;
    try { return chart.renderer.dataWindowReadout(); } catch (e) { return null; }
}

// ============================================================================
// 画线同步（R4 乙案）：state.drawings 双格式读 → Vela doc → drawings.fromJSON（深拷贝）
// ============================================================================
const DRAW_TYPE_MAP = { hline: 'hline', trend: 'trendline', trendline: 'trendline', ray: 'ray', box: 'box' };
function _toVelaDrawing(d) {
    const type = DRAW_TYPE_MAP[d.type];
    if (!type) { console.warn('[ak] drawing type skipped (outside whitelist):', d.type); return null; }
    let anchors = d.anchors ? clone(d.anchors) : (d.points || []).map(p => ({ time: p.time, price: p.price }));
    if (!anchors.length) return null;
    if (type === 'hline') {
        const last = (state.ohlcv || [])[(state.ohlcv || []).length - 1];
        anchors = [{ time: (last && last.timestamp) || Date.now(), price: anchors[0].price }];
    }
    return {
        id: d.id, type, paneId: 'price', anchors,
        style: d.style ? clone(d.style) : {
            lineColor: d.color || '#ef5350', color: d.color || '#ef5350',
            lineWidth: d.line_width || d.lineWidth || 2, width: d.line_width || d.lineWidth || 2,
            lineStyle: LS(d.line_style !== undefined ? d.line_style : d.lineStyle),
        },
        locked: !!d.locked, visible: d.visible !== false && d.visible !== null,
        text: d.text || undefined,
    };
}
export function syncDrawings() {
    if (!chart || !chart.drawings || !chart.drawings.supported) return;
    const doc = { version: 1, drawings: [] };
    Object.values(state.drawings || {}).forEach(d => { const v = _toVelaDrawing(d); if (v) doc.drawings.push(v); });
    try { chart.drawings.fromJSON(clone(doc)); } catch (e) { console.warn('[ak] drawings.fromJSON:', e.message); }
}

// ---- 标记（R4 方案甲：marks lane + panel reason 通道） ----
let _marksGroupDefined = false;
export function syncMarks() {
    if (!chart || !chart.marks) return;
    if (!_marksGroupDefined) { try { chart.marks.defineGroup({ id: 'trades', label: 'Trades' }); _marksGroupDefined = true; } catch (e) {} }
    const marks = (state.markers || []).map((m, i) => {
        const time = m.time < 1e11 ? m.time * 1000 : m.time;
        const isBuy = /buy|long|entry|B/i.test(String(m.text || m.shape || ''));
        const items = [];
        if (m.text) items.push({ type: 'field', label: 'tag', value: String(m.text) });
        if (m.reason) items.push({ type: 'field', label: 'reason', value: String(m.reason) });
        return {
            id: 'mk-' + i, time, group: 'trades', tooltip: m.text || '',
            glyph: { shape: 'circle', color: m.color || (isBuy ? '#26a69a' : '#ef5350'), letter: String(m.text || (isBuy ? 'B' : 'S')).slice(0, 1) },
            content: items.length ? { panel: { items } } : undefined,
        };
    });
    try { chart.marks.set(marks); } catch (e) { console.warn('[ak] marks.set:', e.message); }
}

// ---- 画线工具桥 + 写回（乙案透传 _schema:'vela1'） ----
export function setDrawToolCore(tool) {
    if (!chart || !chart.drawings) return;
    const vtype = DRAW_TYPE_MAP[tool] || tool;
    try { chart.drawings.setTool(chart.drawings.getTool() === vtype ? null : vtype); } catch (e) {}
}
let _writebackBound = false;
export function bindDrawingWriteback() {
    if (_writebackBound || !chart) return;
    _writebackBound = true;
    const q = `board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`;
    chart.on('drawing:created', (e) => {
        const d = (chart.drawings.all() || []).find(x => x.id === (e && e.id));
        if (d && !state.drawings[d.id]) {
            fetch('/api/drawing', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ board_id: state.currentBoard, timeframe: state.currentTimeframe, drawing: Object.assign(clone(d), { _schema: 'vela1' }) }) }).catch(() => {});
        }
    });
    chart.on('drawing:edited', (e) => {
        const d = (chart.drawings.all() || []).find(x => x.id === (e && e.id));
        if (d) fetch(`/api/drawing/${encodeURIComponent(d.id)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board_id: state.currentBoard, timeframe: state.currentTimeframe, patch: clone(d) }) }).catch(() => {});
    });
    chart.on('drawing:removed', (e) => {
        const id = e && e.id;
        if (id && state.drawings[id]) fetch(`/api/drawing/${encodeURIComponent(id)}?${q}`, { method: 'DELETE' }).catch(() => {});
    });
}

export function destroyChartCore() { _destroyChart(); }
