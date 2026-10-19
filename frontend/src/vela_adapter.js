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
import { getLayerPref, setLayerPref, getLayerInputs, setLayerInputs } from './chart_layers_prefs.js';

const V = window.Vela;

// ---- 常量与工具 ----
const MAIN_H = 450;          // 主图固定像素高（0.4 产品承诺）
const VOL_H = 110;           // 成交量常驻窗格
const VOL_UP = 'rgba(38,166,154,0.6)';    // 0.4 成交量涨跌色（P2 起经原生 volume 输入项配置）
const VOL_DOWN = 'rgba(239,83,80,0.6)';
const ms = (bar) => bar.timestamp;                       // state.ohlcv.timestamp 已是 ms
const LS = (n) => (n === 1 ? 'dotted' : n === 2 ? 'dashed' : 'solid');   // LWC 0/1/2 → Vela
const clone = (o) => JSON.parse(JSON.stringify(o));       // §10-⑤ 活引用硬约定

// P2：中间层视觉权威（kind/颜色/fills/circles）；V1：原生保真调色 + 逐点色策略
import { visualSpec, effectiveStyle, effectiveFill, NATIVE_INK } from './visual_spec.js';

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
// 指标渲染唯一通道（官方 emit port，PoC P1 路径 A）：Python 引擎算值 → 本层直喂。
//   P3 起 native 双源退役：**全部**指标（叠加+副图）都走本通道，显示 ≡ AI ≡ Python 单源。
//   成交量例外：走 Vela 原生 volume 指标（store 驱动，非计算指标）。
//   type name = group key（ctx.id 为 native-N 不可靠，§10-9 + p9 探针复证）。
// ============================================================================
const _emitGroups = {};        // groupKey#ctxId → ctx
// ============================================================================
// P3 组模型（单源 emit，native 双源退役）：
//   叠加指标 = **每实例一个组** `ak-ov::<instId>`（paneHint price / overlay / legend:true）
//     → 图例按指标出行（搬运算例不再丢原生图例读数）；隐藏 = 卸载整组（图例行同时消失）。
//   副图 = **每副图一个组** `ak-sub::<name>`（paneHint new / legend:true），容纳该副图全部实例。
//   旧模型（叠加指标全挤一个 ak-main + legend:false）= 图例读数丢失，故换。
//   组 type 名即分组键（ctx.id 为 native-N 不可靠，§10-9 / p9 探针复证：
//   addNativeIndicator(type,{id,title}) 对 registerNativeIndicator 类型**不生效**）。
// ============================================================================
const OV = 'ak-ov::';
const SUB = 'ak-sub::';
function groupOfInstance(instId, ind) { return (ind && ind.subplot) ? SUB + ind.subplot : OV + instId; }
function _groupSeries(groupKey) {
    const series = [];
    const fills = [];   // P2：bb 上下轨填充带（NativeIndicatorOutput.fills）
    const priceLines = [];   // P3：水平线（rsi 阈值 / macd 零轴）
    const polylines = [];   // v0.5.3：折线（zigzag 腿）
    // V1：逐点色策略需要「同 bar 收盘价」（sar 涨/跌判定，与原生 `x < bars[i].close` 同式）。
    //   懒建 time→close 索引：只有声明了 pointColor 的规格（当前 sar）才会触发。
    let _closeByTime = null;
    const closeOf = (t) => {
        if (_closeByTime == null) {
            _closeByTime = new Map();
            (state.ohlcv || []).forEach(b => _closeByTime.set(b.timestamp, b.close));
        }
        return _closeByTime.get(t);
    };
    const pushInd = (ind, instId) => {
        const vis = state.visibility[instId] !== false;
        // P2-fix 隐藏：隐藏指标整体不 emit（series+fills 都不发），Vela diff 卸载 → 真隐藏。
        //   不能靠 visible:false——emit patch 不消费 visible 变化，且 Fill 无 visible 位（锚点 hidden 仍供值，带照画）。
        //   关键：隐藏也要登记 _emitLines（按应有线数）——否则 ws.js hadSeries=false → 每 tick renderChart 整图重建 → 闪。
        if (!vis) {
            _emitLines[instId] = (ind.lines && ind.lines.length) ? ind.lines.length : (ind.values != null ? 1 : 0);
            return;
        }
        const times = ind.times || null;   // P1：时间戳契约（引擎随 values 下发）；blob 无 times → off 回退
        const spec = visualSpec(ind.script);          // P2：中间层视觉规格（null → 回退脚本自带 style/type）
        const linesStyle = ind.lines_style || null;   // 实例级线样式覆盖（用户/AI 改色）
        const lines = (ind.lines && ind.lines.length) ? ind.lines : null;
        const nameToId = {};   // 线名 → series id（fills 解析用）
        const nameColor = {};  // 线名 → 生效色（fills follow 派生用：用户改轨色，带色跟着走）
        let count = 0;
        const env = { script: ind.script, params: ind.params || null, closeOf };
        if (lines) {
            const kindOf = (l) => { const lv = spec && spec.lines && spec.lines[l.name]; return (lv && lv.kind) || l.type; };
            const rank = (l) => { const k = kindOf(l); return (k === 'histogram' || k === 'columns' || k === 'bar') ? 0 : 1; };
            [...lines].sort((a, b) => rank(a) - rank(b)).forEach((line, idx) => {
                const id = `${instId}_${idx}`;
                const lname = line.name || `${instId}_${idx}`;
                nameToId[lname] = id;
                // 动态线名（MA Type 切换 / VWAP 多轨 #N）→ 回退到该研究首条线规格
                const lv = (spec && spec.lines && (spec.lines[lname]
                    || spec.lines[Object.keys(spec.lines)[0]])) || null;
                const ov = linesStyle ? linesStyle[lname] : null;
                const s = _lineSpec(id, lname, line.values, line.type, line.style, vis, times, lv, ov, { ...env, idx });
                series.push(s);
                nameColor[lname] = s.style.color;
                count++;
            });
        } else {
            series.push(_lineSpec(instId, ind.display_name || ind.name || instId, ind.values, ind.type, ind.style, vis, times, null, ind.style, env));
            count = 1;
        }
        // bb 填充带：规格按线名引用 → 解析到本实例 series id；色 = override > follow 派生 > 规格静态色
        const sf = spec && spec.fills;
        if (sf) sf.forEach((f, fi) => {
            const from = nameToId[f.from], to = nameToId[f.to];
            if (!from || !to) return;
            const fov = (linesStyle && f.key) ? linesStyle[f.key] : null;
            fills.push({
                id: `${instId}_fill${fi}`, paneId: '', fromSeriesId: from, toSeriesId: to,
                color: effectiveFill(ind.script, f, nameColor[f.follow || f.from], fov),
            });
        });
        // P3：水平线 + 区带（与原生 boundedOscillator 同构：rsi 70/50/30 + 三区、macd 零轴）
        //   区带靠「隐藏 anchor series」撑出 pane 值域（display 只关 pane/legend/dataWindow，
        //   保留 priceScale ⇒ 0..100 进 autoscale，与原生 anchorPlot 逐字同式）。
        const lvl = {};
        Object.entries((spec && spec.thresholds) || {}).forEach(([k, d]) => {
            const pv = (ind.params || {})[k];
            lvl[k] = Number(typeof d === 'function' ? d(ind.params || {}) : (pv != null ? pv : d));
        });
        Object.entries((spec && spec.axis) || {}).forEach(([k, v]) => { lvl[k] = Number(v); });
        const lvlVal = (x) => (lvl[x] != null ? lvl[x] : Number(x));
        const timeArr = (times && times.length) ? times : (state.ohlcv || []).map(b => b.timestamp);
        if (spec && spec.levels) spec.levels.forEach((L, li) => {
            const price = lvlVal(L.at);
            if (!Number.isFinite(price)) return;
            const lov = (linesStyle && L.key) ? linesStyle[L.key] : null;
            priceLines.push({
                id: `${instId}_pl${li}`, paneId: '', price, title: L.title || '',
                color: (lov && lov.color) || L.color || NATIVE_INK.NEUTRAL,
                lineStyle: L.lineStyle || 'solid', width: 1,
            });
        });
        // v0.5.3：脚本自带水平线（参数相关阈值，如 MFI 80/20）——与规格线去重后合并
        (ind.levels || []).forEach((L, li) => {
            const price = Number(L.price);
            if (!Number.isFinite(price)) return;
            const dup = priceLines.some(pl => Math.abs(pl.price - price) < 1e-9
                && (pl.title || '') === (L.title || ''));
            if (dup) return;
            priceLines.push({
                id: `${instId}_ipl${li}`, paneId: '', price,
                title: L.title || '', color: L.color || NATIVE_INK.NEUTRAL,
                lineStyle: L.lineStyle || 'dashed', width: 1,
            });
        });
        if (spec && spec.zones) {
            const anchorId = {};
            spec.zones.forEach(z => [z.from, z.to].forEach(end => {
                const key = String(end);
                if (anchorId[key] !== undefined) return;
                const val = lvlVal(key);
                if (!Number.isFinite(val)) { anchorId[key] = null; return; }
                const aid = `${instId}_anc_${key}`;
                anchorId[key] = aid;
                series.push({
                    id: aid, title: `${key} anchor`, paneId: '', kind: 'line',
                    points: timeArr.map(tt => ({ time: tt, value: val })),
                    display: { pane: false, legend: false, dataWindow: false },
                    style: { color: 'rgba(120,123,134,0)', width: 1, lineStyle: 'solid' },
                });
            }));
            spec.zones.forEach((z, zi) => {
                const a = anchorId[String(z.from)], b = anchorId[String(z.to)];
                if (!a || !b) return;
                fills.push({ id: `${instId}_zone${zi}`, paneId: '', fromSeriesId: a, toSeriesId: b, color: z.color });
            });
        }
        // v0.5.3：指标自带 markers（williams-fractal）→ series.kind='markers'
        if (Array.isArray(ind.markers) && ind.markers.length) {
            series.push({
                id: `${instId}_markers`, title: ind.display_name || instId, paneId: '',
                kind: 'markers',
                markers: ind.markers.map(m => ({
                    time: Number(m.time), position: m.position,
                    shape: m.shape || 'circle',
                    color: m.color || (m.position === 'belowBar' ? NATIVE_INK.BULLISH : NATIVE_INK.BEARISH),
                    ...m.text ? { text: m.text } : {},
                })),
            });
            count++;
        }
        // v0.5.3：指标自带折线（zigzag）→ NativeIndicatorOutput.polylines
        (ind.polylines || []).forEach((p, pi) => {
            const pts = (p.points || []).map(pt => ({
                xloc: 'bar_time', x: Number(pt.x), price: Number(pt.price),
            })).filter(pt => Number.isFinite(pt.x) && Number.isFinite(pt.price));
            if (pts.length < 2) return;
            const rising = pts[pts.length - 1].price >= pts[0].price;
            polylines.push({
                id: `${instId}_poly${pi}`, paneId: '',
                points: pts, curved: false, closed: false,
                lineColor: p.lineColor || (rising ? NATIVE_INK.BULLISH : NATIVE_INK.BEARISH),
                lineWidth: p.lineWidth || 1, lineStyle: 'solid',
            });
        });
        // 只有折线的指标（zigzag）也要登记「有内容」，否则 ws 每 tick 判空 → 整图重建
        if (polylines.length) count += polylines.length;
        _emitLines[instId] = count;   // P2：emit 注册表（取代 seriesMap 占位）
    };
    const isSub = groupKey.startsWith(SUB);
    const subName = isSub ? groupKey.slice(SUB.length) : null;
    const onlyId = isSub ? null : groupKey.slice(OV.length);
    Object.entries(state.indicators || {}).forEach(([instId, ind]) => {
        if (isSub ? (ind.subplot === subName) : (instId === onlyId)) pushInd(ind, instId);
    });
    return { series, fills, priceLines, polylines };
}
function _colorRuleInk(rule, v, ctx) {
    const ink = ctx.ink || {};
    const prev = ctx.prev;
    switch (rule) {
        case 'sign': return v >= 0 ? ink.pos : ink.neg;
        case 'slope': return prev == null ? null : v > prev ? ink.up : v < prev ? ink.down : (ink.flat || null);
        case 'slope2': return prev == null ? null : v >= prev ? ink.up : ink.down;
        case 'mid': return v >= 0.5 ? ink.above : ink.below;
        case 'close': {
            const c = ctx.close;
            return c == null ? null : (c >= v ? ink.above : ink.below);
        }
        case 'momentum': return v >= 0
            ? (prev != null && v < prev ? ink.fallAbove : ink.growAbove)
            : (prev != null && v < prev ? ink.fallBelow : ink.growBelow);
        case 'absSlope': return prev == null ? null : Math.abs(v) > Math.abs(prev) ? ink.grow : ink.shrink;
        default: return null;
    }
}
function _lineSpec(id, title, values, type, style, vis, times, lv, override, env) {
    style = style || {}; lv = lv || {}; override = override || {}; env = env || {};
    // V1：生效样式统一由 visual_spec.effectiveStyle 求解（渲染 ≡ 设置弹窗初值，单一优先级链）
    //   优先级：实例 override(lines_style) > 中间层规格（原生默认色）> 脚本 style > 默认
    const eff = effectiveStyle(env.script, title, style, override, env.idx, type);
    // kind：中间层视觉规格 > 脚本 type > 默认 line（P2 视觉层收归；circles=sar 圆点，columns=原生柱）
    const ksrc = eff.kind;
    const kind = (ksrc === 'histogram' || ksrc === 'bar') ? 'histogram'
        : ksrc === 'columns' ? 'columns'
        : ksrc === 'area' ? 'area' : ksrc === 'circles' ? 'circles'
        : ksrc === 'cross' ? 'cross'
        : ksrc === 'step' ? 'step' : 'line';   // baseline 降级 line（§10-⑭）
    const color = eff.color;
    const width = eff.lineWidth;
    const lstyle = LS(eff.lineStyle);
    const autoColor = eff.autoColor;
    const vals = values || [];
    // P1 时间戳契约：优先用引擎随 values 同载荷下发的 times（两者同源恒一致，prepend/竞态免疫）。
    //   对 times 尾对齐（toff 仅脚本返回短于 feed 时非零；times 权威无竞态，区别于旧 bars.length）。
    //   无 times（冻结 blob）→ 回退旧 off=bars.len-values.len 索引对齐（blob 时间戳迁移留待后续统一）。
    let timeAt;
    if (times && times.length) {
        const toff = Math.max(0, times.length - vals.length);
        timeAt = (i) => times[toff + i];
    } else {
        const bars = state.ohlcv || [];
        const off = Math.max(0, bars.length - vals.length);
        timeAt = (i) => { const b = bars[off + i]; return b ? ms(b) : i; };
    }
    // 逐点色（Vela SeriesPoint.color）：规格策略优先（sar 涨跌 / macd 动能四态 / rsi 阈值渐变），
    //   用户显式挑了单色（eff.flat）则停用策略，尊重用户颜色；柱状无策略时回退原生涨跌二色。
    const strat = (lv.pointColor && !eff.flat) ? lv.pointColor : null;
    const points = vals.map((v, i) => {
        const time = timeAt(i);
        const pt = { time, value: (v == null ? null : v) };
        if (v == null) return pt;
        let c = null;
        if (strat) {
            c = strat(v, {
                i, prev: vals[i - 1], params: env.params, ink: eff.inks, autoColor,
                close: env.closeOf ? env.closeOf(time) : null,
            });
        }
        // v0.5.3：generated visual spec 的逐点色规则（原生 plot.colors 反推；用户改单色则停用）
        if (!c && lv.colorRule && !eff.flat) {
            c = _colorRuleInk(lv.colorRule, v, {
                prev: vals[i - 1], ink: eff.inks,
                close: env.closeOf ? env.closeOf(time) : null,
            });
        }
        if (!c && (kind === 'histogram' || kind === 'columns') && autoColor) {
            c = v >= 0 ? NATIVE_INK.BULLISH : NATIVE_INK.BEARISH;
        }
        if (c) pt.color = c;
        return pt;
    });
    return { id, title, paneId: '', kind, points, visible: vis,
             style: { color, width, lineStyle: lstyle } };
}
const _registeredTypes = new Map();   // type → 注册时 title（title 变 = 指标改名 → 重注册）
// 返回 true = 本次发生注册/重注册（调用方据此决定是否需要重挂载该组）
function _ensureType(type, title, paneHint, overlay, legend) {
    if (_registeredTypes.get(type) === title) return false;
    if (_registeredTypes.has(type)) { try { V.unregisterNativeIndicator(type); } catch (e) {} }
    _registeredTypes.set(type, title);
    V.registerNativeIndicator({
        type, title, paneHint, overlay, legend, multiInstance: true,
        inputsSchema: () => [], defaultInputs: () => ({}),
        create: () => ({
            start(ctx) { _emitGroups[type + '#' + ctx.id] = ctx; _emitOne(type, ctx); ctx.setStatus('live'); },
            onBars() {}, setInputs() {}, suspend() {}, resume() {},
            stop() { Object.keys(_emitGroups).forEach(k => { if (k.startsWith(type + '#')) delete _emitGroups[k]; }); },
        }),
    });
    return true;
}
function _emitOne(groupKey, ctx) {
    const g = _groupSeries(groupKey);
    ctx.emit({ series: g.series, fills: g.fills, priceLines: g.priceLines,
               polylines: g.polylines });
}
function reEmit(groupKey) {
    Object.entries(_emitGroups).forEach(([k, ctx]) => { if (k.startsWith(groupKey + '#')) _emitOne(groupKey, ctx); });
}
// P3：全部活体组重发（前插/换周期等结构性变化后）；成交量走原生 volume，不在其中
function reEmitAllGroups() {
    [...new Set(Object.keys(_emitGroups).map(k => k.slice(0, k.lastIndexOf('#'))))].forEach(reEmit);
}
export function refreshEmittedGroups() { reEmitAllGroups(); }
let _emitLines = {};   // instId -> 已 emit 线数（结构变化判定，取代 state.seriesMap）
let _styleSig = {};    // V1：instId -> 样式签名（改色/线宽/填充 → 重挂载重绘判定）
export function legacySeriesCount(instId) { return _emitLines[instId] || 0; }

// ============================================================================
// 单图表活体 + 动态总高 relayout（产品承诺实现）
// ============================================================================
let chart = null;
let _chartReady = false;
let _vpvrOn = false;        // v0.5.4：按板记住的 VPVR 原生图层显隐
let _vpvrHandle = null;
let _vpvrLegendObs = null;  // Vela 原生 legend 行（VRVP）隐藏观察器

// ============================================================================
// v0.5.4 最新价越界贴边
// 原生 chrome 在最新价超出可见价格区间时直接跳过标签（drawPriceLineAndCountdown 早退）。
// 这里包一层 chrome 绘制：仍走原生画布/字号/价格色，只在越界时把标签钉在 pane 顶/底并加箭头。
// 版本锁定 0.8.4 的内部 chrome 接口；缺失/异常时退回原生行为，不影响图表。
// ============================================================================
let _lastPricePinState = null;

function _lastPriceDecimals(scale, heightPx) {
    if (!(scale.max > scale.min)) return 2;
    const target = Math.max(2, Math.min(16, Math.round(heightPx / 50)));
    const raw = (scale.max - scale.min) / Math.max(1, target);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const d = Math.max(0, Math.min(8, -Math.floor(Math.log10(step)) + 1));
    return d === 0 ? 2 : d;
}

function _lastPriceText(scale, heightPx, value) {
    // 与 Vela formatPriceLabel 同规则：宽对数轴按量级定小数，常规轴按刻度密度
    if (scale.log && Math.log10(scale.max) - Math.log10(scale.min) >= 1.1) {
        const a = Math.abs(value);
        const d = a >= 100 ? 0 : a >= 1 ? 2 : a >= 0.01 ? 4 : 6;
        return value.toFixed(d === 0 ? 2 : d);
    }
    return value.toFixed(_lastPriceDecimals(scale, heightPx));
}

// percent/indexed 轴与原生 formatPct/formatIndex 同式；基线缺失时退回价格
function _lastPriceAxisText(scene, pricePane, scale, heightPx, value) {
    const mode = pricePane.kind === 'price' ? scene.scaleMode : pricePane.scaleMode;
    const baseline = pricePane.percentBaseline;
    if ((mode === 'percent' || mode === 'indexed')
        && Number.isFinite(baseline) && baseline !== 0) {
        if (mode === 'indexed') return (value / baseline * 100).toFixed(2);
        const pct = (value / baseline - 1) * 100;
        return `${pct >= 0 ? '+' : '-'}${Math.abs(pct).toFixed(2)}%`;
    }
    return _lastPriceText(scale, heightPx, value);
}

// 与 Vela tagTextColor 同式（hex 输入；主题涨跌色都是深色，白字兜底）
function _lastPriceTextColor(bg) {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(bg || '');
    if (!m) return '#ffffff';
    let hex = m[1];
    if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
    const lin = (v) => {
        const c = parseInt(v, 16) / 255;
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    const L = 0.2126 * lin(hex.slice(0, 2)) + 0.7152 * lin(hex.slice(2, 4))
        + 0.0722 * lin(hex.slice(4, 6));
    return L >= 0.4 ? '#000000' : '#ffffff';
}

function _bindLastPricePin() {
    if (!chart) return;
    let renderer = null;
    try { renderer = chart.orchestrator && chart.orchestrator.renderer; } catch (e) { return; }
    const chrome = renderer && renderer.chrome;
    if (!chrome || chrome.__akLastPricePin) return;
    const orig = chrome.drawPriceLineAndCountdown;
    if (typeof orig !== 'function') return;
    chrome.drawPriceLineAndCountdown = function (ctx, scene, coords, theme, dataW, pricePane) {
        orig.call(this, ctx, scene, coords, theme, dataW, pricePane);
        try { _drawLastPricePin(ctx, scene, coords, theme, dataW, pricePane, this); } catch (e) {}
    };
    chrome.__akLastPricePin = true;
    try { window.__ak.lastPricePin = () => _lastPricePinState; } catch (e) {}
    try { renderer.scheduler.invalidate(4); } catch (e) {}
}

function _drawLastPricePin(ctx, scene, coords, theme, dataW, pricePane, chrome) {
    _lastPricePinState = null;
    if (!pricePane || !scene || scene.showPriceLabel === false || scene.candlesHidden) return;
    const bars = scene.bars || [];
    const last = bars[bars.length - 1];
    if (!last || !Number.isFinite(last.close)) return;
    const s = pricePane.scale, b = pricePane.bounds;
    if (!s || !b || !(s.max > s.min) || !(b.height > 0) || pricePane.collapsed) return;
    if (s.log && !(s.min > 0)) return;
    const above = last.close > s.max;
    const below = last.close < s.min;
    if (!above && !below) return;
    const pinTop = s.invert ? below : above;   // 倒置轴时高价在下
    let color = '';
    try { color = chrome.priceElementColor(scene, coords, theme, last); } catch (e) {}
    if (!color) {
        color = last.close >= last.open
            ? (theme && theme.upColor) || '#089981'
            : (theme && theme.downColor) || '#f23645';
    }
    const text = `${above ? '▲' : '▼'} ${_lastPriceAxisText(scene, pricePane, s, b.height, last.close)}`;
    const axisW = ctx.canvas.width / (coords.devicePixelRatio || 1) - dataW;
    if (!(axisW > 0)) return;
    ctx.save();
    const font0 = ctx.font;
    const m = /(\d+(?:\.\d+)?)px/.exec(font0);
    let px = m ? parseFloat(m[1]) : 11;
    let tw = ctx.measureText(text).width;
    while (tw + 8 > axisW && px > 8) {
        px -= 0.5;
        ctx.font = m ? font0.replace(/(\d+(?:\.\d+)?)px/, `${px}px`) : `${px}px sans-serif`;
        tw = ctx.measureText(text).width;
    }
    const w = Math.min(axisW, tw + 8);
    const top = pinTop ? b.top + 1 : b.top + b.height - 17;
    ctx.fillStyle = color;
    ctx.fillRect(dataW + 1, top, w, 16);
    ctx.fillStyle = _lastPriceTextColor(color);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, dataW + 1 + w / 2, top + 8);
    ctx.restore();
    _lastPricePinState = { text, top, width: w, color, above };
}

function _destroyChart() {
    _lastPricePinState = null;
    _vpvrHandle = null;
    if (_vpvrLegendObs) { try { _vpvrLegendObs.disconnect(); } catch (e) {} _vpvrLegendObs = null; }
    if (chart) { try { chart.destroy(); } catch (e) {} }
    chart = null;
    _chartReady = false;
    _volMoved = false;
    Object.keys(_emitGroups).forEach(k => delete _emitGroups[k]);
}

// ---- VPVR 原生图层（v0.5.4）：单实例 overlay，随板记住显隐/输入 ----
export function isVpvrEnabled() { return _vpvrOn; }

// 原生 legend 行隐藏：内置 vpvr descriptor 没开 legend:false，但设置面板要依赖 legend 行，
// 所以保留 DOM、只把「VRVP」那一行 display:none；chip 的 ⚙ 仍可 openIndicatorSettings。
function _hideVpvrLegend() {
    if (!_vpvrOn || !chart) return;
    const root = document.getElementById('main-chart');
    if (!root) return;
    try {
        const leaf = [...root.querySelectorAll('span')]
            .find(e => e.children.length === 0 && e.textContent.trim() === 'VRVP');
        const row = leaf && leaf.closest('div');
        if (row && row.style.display !== 'none') row.style.display = 'none';
    } catch (e) {}
}

function _watchVpvrLegend() {
    if (_vpvrLegendObs || !chart || !_vpvrOn) return;
    const root = document.getElementById('main-chart');
    if (!root) return;
    try {
        _vpvrLegendObs = new MutationObserver(() => _hideVpvrLegend());
        _vpvrLegendObs.observe(root, {
            childList: true, subtree: true, attributes: true, attributeFilter: ['style'],
        });
    } catch (e) { _vpvrLegendObs = null; }
    _hideVpvrLegend();
}

export function openVpvrSettings() {
    if (!chart) return;
    const open = () => {
        if (chart && _vpvrHandle) {
            try { chart.renderer.openIndicatorSettings(_vpvrHandle.id); } catch (e) {}
        }
    };
    if (!_vpvrHandle) {
        // 关闭态点 ⚙：先开图层，等 legend 行挂载后再进设置（否则 open 是 no-op）
        setVpvrEnabled(true);
        requestAnimationFrame(open);
        return;
    }
    open();
}

function _saveVpvrInputs() {
    if (!chart || !_vpvrOn) return;
    try {
        const h = (chart.indicators() || []).find(x => x.nativeType === 'vpvr');
        if (h && h.inputValues) setLayerInputs(state.currentBoard, 'vpvr', h.inputValues());
    } catch (e) {}
}

export function setVpvrEnabled(on) {
    _vpvrOn = !!on;
    setLayerPref(state.currentBoard, 'vpvr', _vpvrOn);
    _syncVpvrLayer();
}

function _syncVpvrLayer() {
    if (!chart || !_chartReady) return;   // 建图完成后 ready 回调里会再同步
    try {
        const existing = (chart.indicators() || []).find(h => h.nativeType === 'vpvr');
        if (_vpvrOn) {
            if (!existing) {
                const h = chart.addNativeIndicator('vpvr');
                _vpvrHandle = h;
                const saved = getLayerInputs(state.currentBoard, 'vpvr');
                if (saved) { try { h.setInputs(saved); } catch (e) {} }
                requestAnimationFrame(_watchVpvrLegend);
            } else {
                _vpvrHandle = existing;
            }
        } else if (existing) {
            try { existing.remove(); } catch (e) {}
            _vpvrHandle = null;
            if (_vpvrLegendObs) { try { _vpvrLegendObs.disconnect(); } catch (e) {} _vpvrLegendObs = null; }
        }
    } catch (e) {
        console.warn('[ak] VPVR toggle failed:', e && e.message);
    }
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
    syncToolbarSticky();
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
    _emitLines = {};                               // P2：emit 注册表随重建清空
    _styleSig = {};                                // V1：样式签名随重建清空（重建后首帧不算「改样式」）
    _destroyChart();                               // P3：组类型由 syncEmitGroups 按需注册（title 跟随显示名）
    _vpvrOn = getLayerPref(state.currentBoard, 'vpvr');
    const container = document.getElementById('main-chart');
    if (!container) return;
    container.innerHTML = '';
    chart = new V.Vela(container, {
        symbol: chartSymbol(),
        timeframe: state.currentTimeframe || '1d',
        theme: 'dark', live: true, volume: true,   // P2：成交量交原生 volume 指标（独立 pane，store 驱动恒对齐）
        currentPriceLine: true,            // 原生最新价轴标签（替代 0.4 自绘吸附标签）
        drawings: true,                    // 0.5.2：Vela 原生工具栏（7 组 79 工具，44px 停靠）
    }, { dataFeed: feed });
    // 探针/控制台把手（e2e 与人工排障；不参与业务逻辑）
    try { window.__ak = { chart, drawings: () => (chart.drawings ? chart.drawings.all() : []) }; } catch (e) {}
    try { chart.renderer.set('attribution', false); } catch (e) {}   // 归因甲案（R6-2）
    _bindLastPricePin();   // v0.5.4：越界贴边标签包在原生 chrome 绘制里
    chart.on('indicator:inputs', () => _saveVpvrInputs());
    chart.on('viewport:changed', () => _viewportCbs.forEach(cb => cb()));
    chart.on('history:complete', () => { _backfillActive = false; clearTimeout(_backfillActiveT); });
    chart.on('history:progress', () => _markBackfillActive());
    _bindCrosshairBridge(chart);
    chart.ready().then(() => {
        if (!chart) return;
        _chartReady = true;
        // P2/P3：原生 volume 由构造选项自动挂载（默认 overlay 在 price pane，0.8.4 paneHint:'price'）；
        // 裁决=独立顶位 pane → moveTo({newPane:true}) 官方入口移入自有 pane，再配 0.4 涨跌色。
        try {
            const vh = (chart.indicators() || []).find(h => h.nativeType === 'volume');
            if (vh && vh.setInputs) vh.setInputs({ upColor: VOL_UP, downColor: VOL_DOWN });
        } catch (e) {}
        syncEmitGroups();         // P3：全部指标（叠加+副图）单源 emit 组挂载 + 布局
        _syncVpvrLayer();
        setTimeout(() => _layoutPanes(), 400);   // 补捉晚于 ready 的 volume 自动挂载
        _showLatest(200);
        syncDrawings();
        syncMarks();
        bindDrawingWriteback();
        bindDrawPrefs();
        bindToolbarSticky();
        _bindLastPricePin();
    });
}
// P3：emit 组差量同步（叠加=每实例一组 ak-ov::<instId>／副图=每组一 pane ak-sub::<name>）+ relayout
//   · 隐藏 = 不挂载该组（原生 setVisible 的 emit 等价：视觉与图例行一起消失）
//   · 改名 = title 只在注册期生效 → 重注册 + 重挂载刷新图例
//   · 消息序无关（subplot_create 可能先于 indicator_add 到达）
export function syncEmitGroups() {
    if (!chart || !_chartReady) return;    // pre-ready adds are dropped by the framework (evidence: panes=1); defer to ready.then
    const live = (chart.indicators() || []).filter(h => {
        const t = h.nativeType || '';
        return t.startsWith(OV) || t.startsWith(SUB);
    });
    const liveTypes = live.map(h => h.nativeType);
    const remounted = [];   // 因改名重注册而重挂载的组键（调用方据此免去重复重挂载）
    const want = [];
    Object.entries(state.indicators || {}).forEach(([id, ind]) => {
        if (ind.subplot) return;
        if (state.visibility[id] === false) return;   // 隐藏 = 不挂载
        want.push({ type: OV + id, title: ind.display_name || ind.name || id, paneHint: 'price', overlay: true, legend: true });
    });
    Object.entries(state.subplots || {}).forEach(([name, sp]) => {
        const hosts = Object.entries(state.indicators || {}).filter(([, i]) => i.subplot === name);
        // 副图内指标全部隐藏 → 不挂载该组（pane 随之消失，与叠加指标「隐藏即不见」一致）；
        // 空副图（agent 显式建的）仍挂载，保留其语义。
        if (hosts.length && !hosts.some(([id]) => state.visibility[id] !== false)) return;
        const title = hosts.length === 1 ? (hosts[0][1].display_name || name) : ((sp && sp.title) || name);
        want.push({ type: SUB + name, title, paneHint: 'new', overlay: false, legend: true });
    });
    // 卸载多余（删除的指标 / 隐藏的叠加指标 / 删掉的副图）
    live.forEach(h => {
        const t = h.nativeType;
        if (want.some(w => w.type === t)) return;
        try { h.remove && h.remove(); } catch (e) {}
        Object.keys(_emitGroups).forEach(k => { if (k.startsWith(t + '#')) delete _emitGroups[k]; });
    });
    want.forEach(w => {
        const mounted = liveTypes.includes(w.type);
        const reregistered = _ensureType(w.type, w.title, w.paneHint, w.overlay, w.legend);
        if (!mounted) { try { chart.addNativeIndicator(w.type); } catch (e) {} return; }
        if (reregistered) { remountGroup(w.type); remounted.push(w.type); }
    });
    _layoutPanes();
    return remounted;
}
// 兼容名：render.js 的 renderSubplots() 调用点（副图+叠加组同一入口）
export function syncSubplotsCore() { syncEmitGroups(); }
// 重挂载一个组：emit 补丁不触发 native 渲染器重绘（V1 定论）→ remove+add，mount 必然重绘。
//   remove+add 同一同步帧内完成，Vela 批渲染 ⇒ 无感知闪烁。
function remountGroup(groupKey) {
    if (!chart) return;
    try {
        (chart.indicators() || []).filter(h => h.nativeType === groupKey).forEach(h => { try { h.remove(); } catch (e) {} });
        Object.keys(_emitGroups).forEach(k => { if (k.startsWith(groupKey + '#')) delete _emitGroups[k]; });
        chart.addNativeIndicator(groupKey);   // start() 重发当前 _groupSeries（尊重 visibility）→ 重绘
    } catch (e) {}
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
    reEmitAllGroups();   // tick 使 emit 序列末点位移（镜像≡store 不变量下的精确索引对齐）
}
// V1/P3：显隐与改样式的重绘入口。emit 补丁只更新模型、native 渲染器不重绘
//   （resize/setTheme/同区间setVisibleRange/同bar _push/epsilon 均 no-op —— V1 定论）。
//   可靠解 = 组挂载差量（syncEmitGroups：隐藏卸载/显示挂载/改名重注册）+ 必要时重挂载组。
//   remove+add 同一同步帧内完成，Vela 批渲染 ⇒ 无感知闪烁。
// ws.js 用：删除指标前取组键（叠加组=该实例独占；副图组=多实例共享）
export function groupKeyOfInstance(instId) { return groupOfInstance(instId, (state.indicators || {})[instId]); }
// ws.js 用：按组键强制重挂载（emit 补丁不重绘 → 组内少了一条也要重挂载）
export function remountGroupByKey(groupKey) { remountGroup(groupKey); }
export function remountIndicator(instId) {
    if (!chart) return;
    const ind = (state.indicators || {})[instId];
    if (!ind) return;
    const gk = groupOfInstance(instId, ind);
    const mountedNow = (chart.indicators() || []).some(h => h.nativeType === gk);
    syncEmitGroups();   // 差量：新显示=挂载（mount 必然重绘）／隐藏=卸载（remove 亦重绘）
    const mountedAfter = (chart.indicators() || []).some(h => h.nativeType === gk);
    // 组一直在（副图内某条隐藏、或纯样式变化）→ 强制重挂载重绘
    if (mountedNow && mountedAfter) remountGroup(gk);
}

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
    // P2 验证钩子：inspect=Vela 实际挂载的 scene（totals.fills / 各指标 series kind 计数）；
    //   group=本适配层 _groupSeries 产出的 emit 载荷（series kind/色/点数 + fills），验证视觉规格接线。
    inspect: () => { try { return chart && chart.inspect ? chart.inspect() : null; } catch (e) { return null; } },
    // 原始 emit 载荷（series/fills/priceLines），排障用；缺省=第一个活体组
    group: (g) => _groupSeries(g || (Object.keys(_emitGroups)[0] || '').split('#')[0] || (OV + Object.keys(state.indicators || {})[0])),
    groups: () => [...new Set(Object.keys(_emitGroups).map(k => k.split('#')[0]))],
    hvis: () => { try { return (chart && chart.indicators ? chart.indicators() : []).map(h => ({ t: h.nativeType || h.title, v: h.visible })); } catch (e) { return []; } },
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
// V1/P3：视觉签名（显示名 + 色/线宽/线型/autoColor/inks/填充）——判定「这次广播要不要重挂载」
//   含 display_name：图例标题只在类型注册期生效 ⇒ 改名必须重注册 + 重挂载。
function _styleSigOf(ind) {
    return JSON.stringify([ind.display_name || null, ind.style || null, ind.lines_style || null,
        (ind.lines || []).map(l => [l.name, l.type, l.style || null])]);
}
export function updateIndicatorSeriesCore(instId) {
    const ind = (state.indicators || {})[instId];
    if (!ind || !chart) return;
    const gk = groupOfInstance(instId, ind);
    const want = (ind.lines && ind.lines.length) ? ind.lines.length : (ind.values ? 1 : 0);
    // P3：组未挂载（新指标／刚取消隐藏／副图刚建）→ 差量同步即挂载（mount 必然重绘，无需整图重建）
    const mounted = (chart.indicators() || []).some(h => h.nativeType === gk);
    if (!mounted) { syncEmitGroups(); return; }
    // V1/P3：结构变化（线数增减）或样式变化 → 重挂载该组
    //   （emit 补丁只改模型、native 渲染器不重绘 —— 与隐藏 bug 同根因）
    const sig = _styleSigOf(ind);
    const prev = _styleSig[instId];
    _styleSig[instId] = sig;
    if (legacySeriesCount(instId) !== want) { remountGroup(gk); return; }   // 结构变化（线数增减）
    if (prev !== undefined && prev !== sig) {
        // 视觉签名变化：改名 → 组差量同步（重注册 title 时内部已重挂载）；纯改样式 → 直接重挂载
        const remounted = syncEmitGroups() || [];
        if (!remounted.includes(gk)) remountGroup(gk);
        return;
    }
    reEmit(gk);   // 纯数值刷新：数据流本身触发重绘（remount 反而会闪）
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
// 画线（0.5.2 原生化）—— 运行时真源 = Vela DrawingStore，落盘 = 每板一份 doc
//   · 装载 loadDrawings：首启/切板 → fromJSON（会清 history/selection，只在这条路径用）
//   · 远端增量 applyDrawingUpsert/Remove：同 id 同内容 = 本端回显 → 忽略；
//     已有 id → update（保留撤销栈），新 id → 合并后 fromJSON（Vela add() 不接受外部 id）
//   · 本地增量 bindDrawingWriteback：created/edited/removed → state 先行 + REST 持久化
// ============================================================================
function _typeKnown(type) {
    try { return !!(V.getDrawingType && V.getDrawingType(type)); } catch (e) { return false; }
}
// 键序无关深比较：服务端回显把 id 追加到末尾，直接 JSON.stringify 会假阴性
function _stable(o) {
    if (Array.isArray(o)) return '[' + o.map(_stable).join(',') + ']';
    if (o && typeof o === 'object') return '{' + Object.keys(o).sort()
        .filter(k => o[k] !== undefined)
        .map(k => JSON.stringify(k) + ':' + _stable(o[k])).join(',') + '}';
    return JSON.stringify(o === undefined ? null : o);
}
function _toVelaDrawing(d) {
    if (!d || typeof d !== 'object') return null;
    const type = d.type;
    if (!type || !_typeKnown(type)) { console.warn('[ak] drawing skipped (unknown type):', d.type); return null; }
    let anchors = Array.isArray(d.anchors) ? d.anchors : [];
    anchors = anchors.filter(p => p && p.time != null && p.price != null)
        .map(p => ({ time: +p.time, price: +p.price }));
    if (!anchors.length) return null;
    const out = {
        id: d.id, type, paneId: d.paneId || 'price', anchors,
        style: d.style ? { ...d.style } : {},
        locked: !!d.locked, visible: d.visible !== false && d.visible !== null,
        text: d.text || undefined, props: d.props || undefined,
    };
    if (Number.isFinite(d.zIndex)) out.zIndex = d.zIndex;
    if (Number.isFinite(d.createdAt)) out.createdAt = d.createdAt;
    // Vela 的 fib 在 deserialize 时 props 缺 reverse 会默认 true（方向反转）：
    // 用户手画的 fib 序列化自带 reverse；API/MCP 只给 levels 时补 false，保持 0=高点。
    if (out.props && type.startsWith('fib') && out.props.reverse === undefined) {
        out.props = { ...out.props, reverse: false };
    }
    if (Array.isArray(d.showOn)) out.showOn = d.showOn;
    // 单锚点类型只保留第一个锚（防畸形输入让原生 deserialize 失败）
    if (['hline', 'vline', 'hray', 'crossline'].includes(type) && out.anchors.length > 1) {
        out.anchors = out.anchors.slice(0, 1);
    }
    return out;
}
export function drawingsDoc() {
    const doc = { version: 1, drawings: [] };
    Object.values(state.drawings || {}).forEach(d => { const v = _toVelaDrawing(d); if (v) doc.drawings.push(v); });
    return doc;
}
/** 全量装载（首启 / 切板）。fromJSON 清撤销栈与选中——只在整份换源时调用。 */
export function loadDrawings() {
    if (!chart || !chart.drawings || !chart.drawings.supported) return;
    try { chart.drawings.fromJSON(clone(drawingsDoc())); }
    catch (e) { console.warn('[ak] drawings.fromJSON:', e.message); }
}
/** ws 增量：新增/修改。同 id 同内容 = 本端回显 → 忽略。 */
export function applyDrawingUpsert(raw) {
    const doc = _toVelaDrawing(raw);
    if (!doc || !doc.id) return;
    const cur = state.drawings[doc.id];
    if (cur && _stable(_toVelaDrawing(cur)) === _stable(doc)) return;   // 自己的回显
    state.drawings[doc.id] = doc;
    if (!chart || !chart.drawings) return;
    if (cur) {
        try { chart.drawings.update(doc.id, clone(doc)); }
        catch (e) { console.warn('[ak] drawings.update:', e.message); }
        return;
    }
    loadDrawings();   // 新 id：Vela add() 不接受外部 id，整份替换（远端新增，撤销栈让位）
}
/** ws 批量（draw_many）：合并后一次装载。 */
export function applyDrawingsBulk(list) {
    if (!Array.isArray(list) || !list.length) return;
    let changed = false;
    for (const raw of list) {
        const doc = _toVelaDrawing(raw);
        if (!doc || !doc.id) continue;
        const cur = state.drawings[doc.id];
        if (cur && _stable(_toVelaDrawing(cur)) === _stable(doc)) continue;
        state.drawings[doc.id] = doc;
        changed = true;
    }
    if (changed) loadDrawings();
}

/** ws 批量删除（delete_drawings）：一次 removeMany。 */
export function applyDrawingsRemove(ids) {
    if (!Array.isArray(ids) || !ids.length) return;
    const hit = ids.filter(id => state.drawings[id]);
    if (!hit.length) return;
    hit.forEach(id => { delete state.drawings[id]; });
    if (chart && chart.drawings) {
        try { chart.drawings.removeMany(hit); }
        catch (e) { loadDrawings(); }
    }
}

/** ws 增量：删除。 */
export function applyDrawingRemove(id) {
    if (!id || !state.drawings[id]) return;
    delete state.drawings[id];
    if (chart && chart.drawings) { try { chart.drawings.remove(id); } catch (e) {} }
}
function syncDrawings() { loadDrawings(); }

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

// ---- 本地写回：Vela 事件 → state 先行 + REST（服务端广播回来按内容相等丢弃） ----
let _writebackBound = false;
export function bindDrawingWriteback() {
    if (_writebackBound || !chart) return;
    _writebackBound = true;
    const find = id => (chart.drawings.all() || []).find(x => x.id === id);
    chart.on('drawing:created', (e) => {
        const d = find(e && e.id); if (!d) return;
        const doc = _toVelaDrawing(d); if (!doc) return;
        state.drawings[doc.id] = doc;
        // 0.5.2 MCP 面：POST /api/drawing 吃 type/anchors/...（不再吃整份 drawing）
        fetch('/api/drawing', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                board_id: state.currentBoard, type: doc.type, anchors: doc.anchors,
                style: doc.style, text: doc.text, show_on: doc.showOn,
                pane_id: doc.paneId, locked: doc.locked, visible: doc.visible, props: doc.props,
            }) }).catch(() => {});
    });
    chart.on('drawing:edited', (e) => {
        const d = find(e && e.id); if (!d) return;
        const doc = _toVelaDrawing(d); if (!doc) return;
        const prev = state.drawings[doc.id];
        if (prev && _stable(prev) === _stable(doc)) return;   // 远端 update 的回放
        state.drawings[doc.id] = doc;
        fetch(`/api/drawing/${encodeURIComponent(doc.id)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ board_id: state.currentBoard, patch: clone(doc) }) }).catch(() => {});
    });
    chart.on('drawing:removed', (e) => {
        const id = e && e.id; if (!id) return;
        const had = !!state.drawings[id];
        delete state.drawings[id];
        if (had) fetch(`/api/drawing/${encodeURIComponent(id)}?board_id=${encodeURIComponent(state.currentBoard || '')}`,
            { method: 'DELETE' }).catch(() => {});
    });
}

// ---- 画线偏好本地持久化（收藏 / 每工具默认样式 / 命名样式；跨刷新保留） ----
const DRAW_PREF_KEY = 'ak.drawings.prefs.v1';
function bindDrawPrefs() {
    if (!chart || !chart.drawings) return;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(DRAW_PREF_KEY) || 'null'); } catch (e) {}
    if (saved) {
        try { if (Array.isArray(saved.favorites)) chart.drawings.setFavorites(saved.favorites); } catch (e) {}
        try { if (saved.defaults) chart.drawings.setToolDefaults(saved.defaults); } catch (e) {}
        try { if (saved.templates) chart.drawings.setToolTemplates(saved.templates); } catch (e) {}
    }
    const save = () => {
        try {
            localStorage.setItem(DRAW_PREF_KEY, JSON.stringify({
                favorites: chart.drawings.favorites(),
                defaults: chart.drawings.toolDefaults(),
                templates: chart.drawings.toolTemplates(),
            }));
        } catch (e) {}
    };
    chart.on('drawing:favorites', save);
    chart.on('drawing:defaults', save);
    chart.on('drawing:templates', save);
}

export // ---- 画线工具栏滚动吸附 ----
// 原生条是 Vela 画布内的 absolute 层（height:100%），副图把内容撑高后，页面/容器一滚它就跟着走。
// 这里按滚动量反补 top 并把高度收进可视区：滚动越过 OHLC 条带后贴容器顶，底部随内容结束。
let _tbStickyBound = false;
export function syncToolbarSticky() {
    const wrap = document.getElementById('main-chart');
    if (!wrap) return;
    const cont = wrap.closest('.chart-container');
    const tb = wrap.querySelector('.vela-dtb');
    if (!cont || !tb) return;
    const st = cont.scrollTop;
    const off = wrap.offsetTop;              // #main-chart 在滚动内容中的起点（OHLC 条带之后）
    const top = Math.max(0, st - off);       // 越过 OHLC 后固定到容器顶
    const visible = cont.clientHeight - off + st - top;   // 容器底在 wrapper 坐标系里还剩多少
    const h = Math.min(wrap.clientHeight - top, visible);
    const nextTop = top + 'px', nextH = Math.max(120, Math.round(h)) + 'px';
    if (tb.style.top !== nextTop) tb.style.top = nextTop;
    if (tb.style.height !== nextH) tb.style.height = nextH;
}
function bindToolbarSticky() {
    const cont = document.querySelector('.chart-container');
    const wrap = document.getElementById('main-chart');
    if (!cont || !wrap || _tbStickyBound) return;
    _tbStickyBound = true;
    cont.addEventListener('scroll', syncToolbarSticky, { passive: true });
    if (typeof ResizeObserver !== 'undefined') {
        const ro = new ResizeObserver(syncToolbarSticky);
        ro.observe(cont); ro.observe(wrap);
    }
    // 把 Vela 写在挂载容器上的工具栏 gutter 镜像到滚动容器，
    // 供 #ohlc-legend 的 padding-left 与画布内指标图例对齐（折叠时 gutter 变，观察器跟随）。
    const syncGutter = () => {
        const g = wrap.style.getPropertyValue('--vela-toolbar-gutter');
        if (g) cont.style.setProperty('--vela-toolbar-gutter', g);
    };
    syncGutter();
    // 折叠/展开会改 gutter（wrap 的 style 变量）→ 顺带重算吸附高度/位置
    try {
        new MutationObserver(() => { syncGutter(); syncToolbarSticky(); })
            .observe(wrap, { attributes: true, attributeFilter: ['style'] });
    } catch (e) {}
    syncToolbarSticky();
}

function destroyChartCore() { _destroyChart(); }
