// ============================================================================
// vela_adapter.js —— Vela 唯一接触点（v0.5 R2 薄适配层纪律）
// 应用层（ws.js/ui.js/main.js/render.js 胶水面）不得直接摸 window.Vela，全经本文件。
// 兼容基线契约 = docs/v0.5-需求与改动点.md §2 映射表（PoC 0.8.1 验过的 API 面）。
// 注意事项锚点：§10-①..⑧（深拷贝/事件缺/双格式存储等）。
// ============================================================================
import { state } from './state.js';

const V = window.Vela;

// ---- 工具 ----
const ms = (bar) => bar.timestamp;                       // state.ohlcv.timestamp 已是 ms
const LS = (n) => (n === 1 ? 'dotted' : n === 2 ? 'dashed' : 'solid');   // LWC 0/1/2 → Vela
const clone = (o) => JSON.parse(JSON.stringify(o));       // §10-⑤ 活引用硬约定：存档/跨边界必深拷贝

// ============================================================================
// dataFeed 桥（R3）：后端 WS 数据 → Vela MarketDataFeed port
//   load       = 历史（读 state.ohlcv 快照）
//   subscribe  = 实时连接点（applyDataUpdate 经 ingest 推 onBar）
//   零 provider 注册（PoC P2 已验形态）
// ============================================================================
class AkFeed {
    constructor() { this._onBar = null; this._loadWaiters = []; }
    async load(cfg) {
        const bars = (state.ohlcv || []).map(b => ({
            time: ms(b), open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
        }));
        return bars;
    }
    subscribe(cfg, onBar) { this._onBar = onBar; return () => { this._onBar = null; }; }
    destroy() { this._onBar = null; }
    // 实时通道：forming tick / 新 bar 追加
    pushBar(bar) {
        if (this._onBar) this._onBar({ time: ms(bar), open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume });
    }
}
const feed = new AkFeed();

// ============================================================================
// native indicator 通道（PoC P1 路径 A）：values 直喂，零 scripting engine
//   组实例模型：主图叠加组 'ak-main' 单实例 emit 全部主图指标 series；
//              每副图组 'ak-sub::<name>' 单实例 emit 该副图全部指标 series（同副图多线天然）；
//              成交量 'ak-vol' 常驻 columns pane。
// ============================================================================
const _emitGroups = {};        // groupId → ctx（活实例）
function _groupSeries(groupId) {
    const series = [];
    const pushInd = (ind, instId) => {
        const vis = state.visibility[instId] !== false;
        const lines = (ind.lines && ind.lines.length) ? ind.lines : null;
        if (lines) {
            // 柱状垫底、线/面积在上（0.4 zOrdered 语义）
            const rank = (l) => (l.type === 'histogram' || l.type === 'bar') ? 0 : 1;
            [...lines].sort((a, b) => rank(a) - rank(b)).forEach((line, idx) => {
                series.push(_lineSpec(`${instId}_${idx}`, line.name || `${instId}_${idx}`, line.values, line.type, line.style, vis));
            });
        } else {
            series.push(_lineSpec(instId, ind.display_name || ind.name || instId, ind.values, ind.type, ind.style, vis));
        }
    };
    if (groupId === 'ak-vol') {
        series.push({
            id: 'vol', title: 'VOL', paneId: '', kind: 'histogram',
            points: (state.ohlcv || []).map(b => ({
                time: ms(b), value: b.volume,
                color: b.close >= b.open ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
            })),
            style: { color: '#4fc3f7', width: 1, lineStyle: 'solid' },
        });
        return series;
    }
    Object.entries(state.indicators || {}).forEach(([instId, ind]) => {
        const wantSub = groupId === 'ak-main' ? !ind.subplot : (ind.subplot === groupId.slice(7));
        if (wantSub) pushInd(ind, instId);
    });
    return series;
}
function _lineSpec(id, title, values, type, style, vis) {
    style = style || {};
    const kind = (type === 'histogram' || type === 'bar') ? 'histogram'
        : type === 'area' ? 'area' : 'line';          // baseline 降级 line（0.4 罕用，记录遗留）
    const color = style.color || '#4fc3f7';
    const points = (values || []).map((v, i) => {
        const bar = (state.ohlcv || [])[i];
        const pt = { time: bar ? ms(bar) : i, value: (v == null ? null : v) };
        if (kind === 'histogram' && v != null && style.autoColor !== false) {
            pt.color = v >= 0 ? '#26a69a' : '#ef5350';   // 0.4 涨跌自动红绿语义
        }
        return pt;
    });
    return {
        id, title, paneId: '', kind, points, visible: vis,
        style: { color, width: style.lineWidth || 2, lineStyle: LS(style.lineStyle) },
    };
}
function _registerGroupTypes() {
    if (_registerGroupTypes.done) return;
    _registerGroupTypes.done = true;
    const mk = (type, title, paneHint, overlay) => V.registerNativeIndicator({
        type, title, paneHint, overlay, multiInstance: false, legend: false,
        inputsSchema: () => [], defaultInputs: () => ({}),
        create: () => ({
            start(ctx) {
                _emitGroups[type] = ctx;                 // type 名 = group 名（ctx.id=native-N 不可靠）
                ctx.emit({ series: _groupSeries(type) });
                ctx.setStatus('live');
            },
            onBars() {},
            setInputs() {}, suspend() {}, resume() {}, stop() { delete _emitGroups[type]; },
        }),
    });
    mk('ak-main', 'Indicators (overlay)', 'price', true);
    mk('ak-vol', 'Volume', 'new', false);
    // 副图类型按需动态注册（type 名含 subplot name）
}
function _ensureSubType(name) {
    const type = 'ak-sub::' + name;
    if (_registeredSubs.has(type)) return type;
    _registeredSubs.add(type);
    V.registerNativeIndicator({
        type, title: name, paneHint: 'new', overlay: false, multiInstance: false, legend: false,
        inputsSchema: () => [], defaultInputs: () => ({}),
        create: () => ({
            start(ctx) { _emitGroups[type] = ctx; ctx.emit({ series: _groupSeries(type) }); ctx.setStatus('live'); },
            onBars() {}, setInputs() {}, suspend() {}, resume() {}, stop() { delete _emitGroups[type]; },
        }),
    });
    return type;
}
const _registeredSubs = new Set();
function _subNameOf(indId) { return (state.indicators[indId] || {}).subplot || ''; }
function reEmit(groupId) {
    const ctx = _emitGroups[groupId];
    if (ctx) ctx.emit({ series: _groupSeries(groupId) });
}
function reEmitAll() { Object.keys(_emitGroups).forEach(reEmit); }

// ============================================================================
// 图表活体
// ============================================================================
let chart = null;
const _addedInstances = [];      // 本图表活体的 native 实例 id（重建时清）

function _destroyChart() {
    if (chart) { try { chart.destroy(); } catch (e) {} }
    chart = null;
    Object.keys(_emitGroups).forEach(k => delete _emitGroups[k]);
    _addedInstances.length = 0;
}

export function renderChartCore() {
    _registerGroupTypes();
    _destroyChart();
    const container = document.getElementById('main-chart');
    if (!container) return;
    container.innerHTML = '';
    chart = new V.Vela(container, {
        symbol: (state.currentBoard || 'AK') + ':' + (state.currentTimeframe || '1d'),
        timeframe: state.currentTimeframe || '1d',
        theme: 'dark',
        live: true,
        volume: false,                 // 成交量走 ak-vol 独立 pane（0.4 常驻窗格语义）
        currentPriceLine: true,        // 原生最新价轴标签（替代 0.4 自绘吸附标签）
        drawings: { toolbar: false },  // 0.5.0 画线工具栏形态 C3 定（先关，MCP/程序化通道不受影响）
    }, { dataFeed: feed });
    // 归因甲案：关水印（NOTICE 义务由自建外壳页脚声明承担，R6-2）
    try { chart.renderer.set('attribution', false); } catch (e) { /* 老版本无此键则忽略 */ }
    // 视口上报桥（render.js reportView 用）
    chart.on('viewport:changed', () => { _viewportCbs.forEach(cb => cb()); });
    chart.ready().then(() => {
        if (!chart) return;
        // 成交量常驻 pane
        _addInstance('ak-vol', 'ak-vol');
        // 主图叠加组
        _addInstance('ak-main', 'ak-main');
        // 副图组（每 subplot 一实例）
        Object.keys(state.subplots || {}).forEach(name => _addInstance(_ensureSubType(name), 'ak-sub::' + name));
        // 初始视口：最新 200 根（0.4 showLatest 语义）
        _showLatest(200);
        syncDrawings();
        syncMarks();
        bindDrawingWriteback();
    });
}
function _addInstance(type, groupId) {
    try {
        const h = chart.addNativeIndicator(type, { id: groupId });
        _addedInstances.push(groupId);
    } catch (e) { /* 实例已存在等：忽略，_emitGroups 以 ctx.id 为准 */ }
}
function _showLatest(n) {
    const bars = state.ohlcv || [];
    if (!chart || !bars.length) return;
    const from = bars[Math.max(0, bars.length - n)].timestamp;
    const tfMs = _tfMs(state.currentTimeframe);
    chart.setVisibleRange({ from, to: bars[bars.length - 1].timestamp + 2 * tfMs });
}
function _tfMs(tf) {
    const m = { '1m': 60e3, '5m': 300e3, '15m': 900e3, '30m': 1800e3, '1h': 3600e3, '4h': 14400e3, '1d': 86400e3, '1w': 604800e3 };
    return m[tf] || 86400e3;
}

// ---- 实时/增量更新（ws.js applyDataUpdate 语义） ----
export function applyDataUpdateCore(shift = 0) {
    if (!chart) { renderChartCore(); return; }
    const bars = state.ohlcv || [];
    if (!bars.length) return;
    if (shift > 0) {
        // 历史前插：Vela feed 无 head-insert 通道 → setMarket 重载 + 视口时间窗恢复
        const prev = getVisibleTimeRange();
        chart.setMarket({ symbol: chartSymbol(), timeframe: state.currentTimeframe || '1d' })
            .then(() => { if (prev && chart) chart.setVisibleRange(prev); })
            .catch(() => {});
        return;
    }
    // 原地 tick / 新 bar 追加：onBar 通道
    feed.pushBar(bars[bars.length - 1]);
    reEmitAll();                       // 指标 values 随 bar 更新重算重发
}
function chartSymbol() { return (state.currentBoard || 'AK') + ':' + (state.currentTimeframe || '1d'); }

export function updateIndicatorSeriesCore(instId) {
    const ind = (state.indicators || {})[instId];
    if (!ind) return;
    reEmit(ind.subplot ? 'ak-sub::' + ind.subplot : 'ak-main');
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
    chart.setVisibleRange({ from: fromSec * 1000, to: toSec * 1000 });   // 秒→ms 换算（§2 锚点）
}
export function resizeAllChartsCore() { if (chart) { try { chart.resize(); } catch (e) {} } }

// ---- 截图（renderer.screenshot 返回 dataURL string，PoC p8 已验） ----
export function captureSnapshotCore() {
    if (!chart) return null;
    try { return chart.renderer.screenshot(); } catch (e) { return null; }
}

// ---- 十字线读数桥（自绘图例跟随：container mousemove → readout） ----
export function readDataWindow() {
    if (!chart || !chart.renderer || !chart.renderer.dataWindowReadout) return null;
    try { return chart.renderer.dataWindowReadout(); } catch (e) { return null; }
}

// ============================================================================
// 画线同步（R4）：state.drawings 双格式读（points=0.4 结构 / anchors=Vela doc 结构）
//   → 统一转 Vela SerializedDrawing → drawings.fromJSON（深拷贝，§10-⑤）
//   type 白名单起步：hline/trendline/ray/box（§4）；其余类型跳过并日志
// ============================================================================
const DRAW_TYPE_MAP = { hline: 'hline', trend: 'trendline', trendline: 'trendline', ray: 'ray', box: 'box' };
function _toVelaDrawing(d) {
    const type = DRAW_TYPE_MAP[d.type];
    if (!type) { console.warn('[ak] drawing type skipped (outside whitelist):', d.type); return null; }
    // 双格式：anchors 已在 = Vela doc 结构（前端鼠标画线回写路径）；points = 0.4 结构
    let anchors = d.anchors ? clone(d.anchors)
        : (d.points || []).map(p => ({ time: p.time, price: p.price }));   // 0.4 points.time 已是 ms
    if (!anchors.length) return null;
    if (type === 'hline') {
        // 0.4 hline points=[{price}] 无 time：anchor 补当前末 bar 时间（hline 全宽，time 仅定位用）
        const last = (state.ohlcv || [])[ (state.ohlcv || []).length - 1 ];
        anchors = [{ time: (last && last.timestamp) || Date.now(), price: anchors[0].price }];
    }
    return {
        id: d.id, type, paneId: 'price', anchors,
        style: d.style ? clone(d.style) : {
            // Vela 渲染读 lineColor/lineWidth（p3 doc 样例实证）；color/width 并存兼容
            lineColor: d.color || '#ef5350', color: d.color || '#ef5350',
            lineWidth: d.line_width || d.lineWidth || 2, width: d.line_width || d.lineWidth || 2,
            lineStyle: LS(d.line_style !== undefined ? d.line_style : d.lineStyle),
        },
        locked: !!d.locked, visible: d.visible !== false,
        text: d.text,
    };
}
export function syncDrawings() {
    if (!chart || !chart.drawings || !chart.drawings.supported) return;
    const doc = { version: 1, drawings: [] };
    Object.values(state.drawings || {}).forEach(d => {
        const v = _toVelaDrawing(d);
        if (v) doc.drawings.push(v);
    });
    try { chart.drawings.fromJSON(clone(doc)); } catch (e) { console.warn('[ak] drawings.fromJSON:', e.message); }
}

// ============================================================================
// 标记同步（R4 方案甲）：state.markers → chart.marks（group='trades' + glyph + panel）
//   0.4 marker {time(ms|s), position, color, shape, text} → mark glyph（letter 取 text 首字）
//   reason 通道（0.6 六件套）预留：marker.reason 存在则进 panel content
// ============================================================================
let _marksGroupDefined = false;
export function syncMarks() {
    if (!chart || !chart.marks) return;
    if (!_marksGroupDefined) {
        try { chart.marks.defineGroup({ id: 'trades', label: 'Trades' }); _marksGroupDefined = true; } catch (e) {}
    }
    const marks = (state.markers || []).map((m, i) => {
        const time = m.time < 1e11 ? m.time * 1000 : m.time;      // 秒/毫秒自适应（0.4 语义）
        const isBuy = /buy|long|entry|B/i.test(String(m.text || m.shape || ''));
        const items = [];
        if (m.text) items.push({ type: 'field', label: 'tag', value: String(m.text) });
        if (m.reason) items.push({ type: 'field', label: 'reason', value: String(m.reason) });   // 0.6 通道预留
        return {
            id: 'mk-' + i, time, group: 'trades',
            tooltip: m.text || '',
            glyph: { shape: 'circle', color: m.color || (isBuy ? '#26a69a' : '#ef5350'), letter: String(m.text || (isBuy ? 'B' : 'S')).slice(0, 1) },
            content: items.length ? { panel: { items } } : undefined,
        };
    });
    try { chart.marks.set(marks); } catch (e) { console.warn('[ak] marks.set:', e.message); }
}

// ============================================================================
// 画线工具桥 + 用户画线写回（C3）
//   侧栏按钮 → setDrawTool → Vela 原生画线模式（磁吸/手柄/undo 全原生，R5-1 白拿）
//   写回：drawing:created/edited/removed → REST /api/drawing（0.4 结构，anchors→points 反转换）
// ============================================================================
export function setDrawToolCore(tool) {
    if (!chart || !chart.drawings) return;
    const vtype = DRAW_TYPE_MAP[tool] || tool;
    try { chart.drawings.setTool(chart.drawings.getTool() === vtype ? null : vtype); } catch (e) {}
}
function _velaToRest(d) {
    // Vela SerializedDrawing → 0.4 REST 参数（存储单格式=0.4 结构，见 REPORT 决策记录）
    const pts = (d.anchors || []).map(a => ({ time: a.time, price: a.price }));
    return {
        type: Object.keys(DRAW_TYPE_MAP).find(k => DRAW_TYPE_MAP[k] === d.type) || d.type,
        points: d.type === 'hline' ? [{ price: pts[0] && pts[0].price }] : pts,
        color: (d.style && (d.style.lineColor || d.style.color)) || '#ef5350',
        line_width: (d.style && (d.style.lineWidth || d.style.width)) || 2,
        line_style: (d.style && d.style.lineStyle) || 'solid',
        text: d.text || '',
    };
}
let _writebackBound = false;
export function bindDrawingWriteback() {
    if (_writebackBound || !chart) return;
    _writebackBound = true;
    const persist = (d, method) => {
        const body = Object.assign({ board_id: state.currentBoard, timeframe: state.currentTimeframe }, _velaToRest(d));
        const url = method === 'DELETE'
            ? `/api/drawing/${encodeURIComponent(d.id)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`
            : '/api/drawing';
        fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then(r => r.json()).then(res => {
                if (res && res.id && res.id !== d.id) { /* 后端 mint id：前端 doc 与存储 id 可能不同，接受后端为准 */ }
            }).catch(() => {});
    };
    chart.on('drawing:created', (e) => {
        const d = (chart.drawings.all() || []).find(x => x.id === (e && e.id));
        if (d && !state.drawings[d.id]) persist(d, 'POST');
    });
    chart.on('drawing:edited', (e) => {
        const d = (chart.drawings.all() || []).find(x => x.id === (e && e.id));
        if (d) persist(d, 'POST');      // edited 若 fired 则更新写回（p3 未测此名，C3 补验）
    });
    chart.on('drawing:removed', (e) => {
        const id = e && e.id;
        if (id && state.drawings[id]) {
            fetch(`/api/drawing/${encodeURIComponent(id)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`, { method: 'DELETE' }).catch(() => {});
        }
    });
}

export function destroyChartCore() { _destroyChart(); }
export const adapterInfo = { version: 'vela-adapter-0.5.0-c1', vela: V && V.VERSION };
