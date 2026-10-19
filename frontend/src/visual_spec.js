// ============================================================================
// 中间层视觉权威（P2 视觉层收归 + V1 原生保真调色）
// ----------------------------------------------------------------------------
// 原则：指标脚本只出「纯计算值 + 语义线名」，一切视觉（kind/颜色/线宽/填充带/圆点）
// 由本表定义。未列入的脚本（custom 自定义）回退到其自带 lines[].style/type。
//
// 用户裁决（2026-10-18）：搬运原生指标时，**初始颜色配置 = Vela 原生默认**；
// 用户仍可在指标设置面板改（实例 override 优先级最高）。
// 原生默认逐条核对自 tools/vela-regression/package/dist/vela.global.js：
//   bb    bollingerBands  basis=WARNING，上下轨=INFO，fill=transp(INFO,92)
//   sar   parabolicSar    kind=cross，涨=BULLISH/跌=BEARISH，逐点按 value<close 判涨跌
//   macd  macd            MACD线=INFO，信号线=WARNING，柱=columns + momentumColumnColors 四态
//   rsi   rsi             width=2，NEUTRAL 中值向 BULLISH/BEARISH 渐变（rampColors）
//   obv   obv             INFO
//   sma/ema fixedAverage  原生每实例都是 INFO（无多实例调色板）；本产品需多线可区分，
//                         故保留调色板，但色值改用 Vela 自家语义色（首线=INFO≡原生）
//   kdj   无原生对应      按原生 stochastic 对齐：%K=INFO、%D=WARNING；J 取 Vela JAW 紫
// 线宽：原生 plot 未显式给 width 时按 1 渲染（vela.global.js:43981 `width: plot.width ?? 1`）。
//
// 字段：
//   lines[线名] = { kind, color, width, lineStyle, autoColor, inks, pointColor }
//     kind: 'line'|'area'|'histogram'|'columns'|'circles'|'cross'|'step'（缺省 line）
//     inks: {槽名: 色}  多色语义槽（sar 涨跌 / macd 柱四态 / rsi 渐变三段）
//     pointColor(v, ctx) → 色|null   逐点色策略；ctx={i,prev,close,params,ink,autoColor}
//     autoColor: 柱状自动涨跌色开关（缺省 true）
//   fills = [{ key, from:线名, to:线名, color, follow:线名, transparency }]
//     follow+transparency = 跟随某线色派生透明填充（用户改轨色，带色跟着走）
//   axis = { top, bottom }                       副图值域（靠隐藏 anchor series 撑出，原生同法）
//   thresholds = { 名: 默认值 | (params)=>值 }    语义阈值（rsi 超买/超卖/中值）
//   levels = [{ key, at, color, lineStyle, title }]  水平线 → NativeIndicatorOutput.priceLines
//   zones  = [{ key, from, to, color }]              区带填充（from/to=阈值名或数值）→ 隐藏 anchor + fill
//
// 优先级（_lineSpec / effectiveStyle 内）：实例 override(lines_style) > 本规格 > 脚本 style > 默认。
// schema 依据：Vela NativeIndicatorOutput（series + fills），SeriesPoint.color 支持逐点色。
// ============================================================================

// Vela 原生语义色（vela.global.js src/core/palette.ts 常量，逐字核对）
export const NATIVE_INK = {
    ACCENT: '#2962ff',
    BULLISH: '#089981',
    BEARISH: '#f23645',
    NEUTRAL: '#787b86',
    WARNING: '#ff9800',
    INFO: '#5b9cf6',
    JAW: '#ab47bc',       // bands.ts JAW_COLOR（alligator 颚紫）
};
const N = NATIVE_INK;

// Vela transp(hex, transparency)：透明度百分比 → 8 位 hex（与原生同式，vela.global.js:44493）
export function transp(hex, transparency) {
    const m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(String(hex || '').trim());
    if (!m) return hex;
    const a = Math.round(Math.max(0, Math.min(1, (100 - transparency) / 100)) * 255)
        .toString(16).padStart(2, '0');
    return `#${m[1]}${a}`;
}
function channels(c) {
    const m = /^#([0-9a-f]{6})/i.exec(String(c || '').trim());
    if (!m) return null;
    const h = m[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
// Vela gradient(value, low, high, from, to)（vela.global.js:44627）
export function gradient(value, low, high, from, to) {
    const a = channels(from), b = channels(to);
    if (!a || !b || !Number.isFinite(value)) return from;
    const span = high - low;
    const t = span === 0 ? 0 : Math.max(0, Math.min(1, (value - low) / span));
    const mix = (i) => Math.round(a[i] + (b[i] - a[i]) * t).toString(16).padStart(2, '0');
    return `#${mix(0)}${mix(1)}${mix(2)}`;
}
// Vela momentumColumnColors（vela.global.js:44571）：零上/零下 × 上升/下降 四态
function momentumInk(v, prev, ink) {
    const p = (prev != null && Number.isFinite(prev)) ? prev : v;
    const rising = v > p;
    if (v >= 0) return rising ? ink.growAbove : ink.fallAbove;
    return rising ? ink.growBelow : ink.fallBelow;
}
// Vela rampColors（vela.global.js:44552）：低→中→高 三段渐变
function rampInk(v, low, mid, high, ink) {
    return v <= mid ? gradient(v, low, mid, ink.low, ink.mid) : gradient(v, mid, high, ink.mid, ink.high);
}

// 多线（sma/ema）调色板：Vela 自家语义色，首色 = 原生单实例默认 INFO
const MA_PALETTE = [N.INFO, N.WARNING, N.BULLISH, N.BEARISH, N.JAW, N.ACCENT];

export const VISUAL_SPEC = {
    // 布林带：上/中/下三线 + 上下轨填充带（主图叠加）——原生 basis 橙、上下轨蓝、填充蓝 8%
    'indicator/bb': {
        lines: {
            BB_UPPER: { kind: 'line', color: N.INFO, width: 1 },
            BB_MID:   { kind: 'line', color: N.WARNING, width: 1 },
            BB_LOWER: { kind: 'line', color: N.INFO, width: 1 },
        },
        fills: [{
            key: 'fillColor', from: 'BB_UPPER', to: 'BB_LOWER',
            follow: 'BB_UPPER', transparency: 92, color: transp(N.INFO, 92),
        }],
    },
    // 抛物转向：圆点画在蜡烛上下（主图叠加）——原生逐点涨绿/跌红（value<close 为涨）
    // 形态偏差（已记录）：原生 kind='cross'（小十字），本产品沿用 P2 验证过的 circles 圆点。
    'indicator/sar': {
        lines: {
            SAR: {
                kind: 'circles', width: 2, color: N.BULLISH,
                inks: { bull: N.BULLISH, bear: N.BEARISH },
                pointColor: (v, ctx) => (ctx.close == null ? null : (v < ctx.close ? ctx.ink.bull : ctx.ink.bear)),
            },
        },
    },
    // MACD：DIF/DEA 线 + 动能四态柱（副图）——原生 MACD线=INFO、信号线=WARNING、柱=columns、零轴虚线
    'indicator/macd': {
        lines: {
            DIF:  { kind: 'line', color: N.INFO, width: 1 },
            DEA:  { kind: 'line', color: N.WARNING, width: 1 },
            MACD: {
                kind: 'columns', color: N.BULLISH, autoColor: true,
                inks: {
                    growAbove: N.BULLISH, fallAbove: transp(N.BULLISH, 50),
                    growBelow: transp(N.BEARISH, 50), fallBelow: N.BEARISH,
                },
                pointColor: (v, ctx) => (ctx.autoColor ? momentumInk(v, ctx.prev, ctx.ink) : null),
            },
        },
        levels: [{ key: 'zero', at: 0, color: N.NEUTRAL, lineStyle: 'dashed', title: 'Zero Line' }],
    },
    // RSI：单线（副图）——原生宽 2，中值 NEUTRAL 向超卖 BULLISH / 超买 BEARISH 渐变；
    //   并补齐原生 boundedOscillator 的全套视觉：70/50/30 三条水平线 + 超买/超卖区带 + 中带填充，
    //   值域 0..100 由隐藏 anchor series 撑出（display 只关 pane/legend/dataWindow，保留 priceScale）。
    'indicator/rsi': {
        lines: {
            RSI: {
                kind: 'line', color: N.NEUTRAL, width: 2,
                inks: { low: N.BULLISH, mid: N.NEUTRAL, high: N.BEARISH },
                pointColor: (v, ctx) => {
                    const p = ctx.params || {};
                    const os = Number(p.oversold != null ? p.oversold : 30);
                    const ob = Number(p.overbought != null ? p.overbought : 70);
                    return rampInk(v, os, (os + ob) / 2, ob, ctx.ink);
                },
            },
        },
        axis: { top: 100, bottom: 0 },
        thresholds: {
            overbought: 70, oversold: 30,
            mid: (p) => (Number(p.overbought != null ? p.overbought : 70)
                + Number(p.oversold != null ? p.oversold : 30)) / 2,
        },
        levels: [
            { key: 'overbought', at: 'overbought', color: N.NEUTRAL, lineStyle: 'dashed', title: 'Overbought' },
            { key: 'midline', at: 'mid', color: N.NEUTRAL, lineStyle: 'dotted', title: 'Midline' },
            { key: 'oversold', at: 'oversold', color: N.NEUTRAL, lineStyle: 'dashed', title: 'Oversold' },
        ],
        zones: [
            { key: 'obZone', from: 'overbought', to: 'top', color: transp(N.BEARISH, 92) },
            { key: 'osZone', from: 'oversold', to: 'bottom', color: transp(N.BULLISH, 92) },
            { key: 'band', from: 'overbought', to: 'oversold', color: transp(N.NEUTRAL, 90) },
        ],
    },
    // OBV：单线（副图）——原生 INFO
    'indicator/obv': { lines: { OBV: { kind: 'line', color: N.INFO, width: 1 } } },
    // KDJ：K/D/J 三线（副图）——对齐原生 stochastic（%K=INFO、%D=WARNING），J 取 JAW 紫
    'indicator/kdj': {
        lines: {
            K: { kind: 'line', color: N.INFO, width: 1 },
            D: { kind: 'line', color: N.WARNING, width: 1 },
            J: { kind: 'line', color: N.JAW, width: 1 },
        },
    },
    // MA 均线组 / EMA：多线（主图叠加），按 Vela 语义色调色板循环（线名动态 MA5/MA10/…）
    'indicator/sma': { multi: true, kind: 'line', palette: MA_PALETTE, width: 1 },
    'indicator/ema': { multi: true, kind: 'line', palette: MA_PALETTE, width: 1 },
};

// 单线视觉规格查找（按线名）；multi 型（sma/ema）走 paletteByIndex
export function visualSpec(script) { return VISUAL_SPEC[script] || null; }
export function lineVisual(script, lineName) {
    const s = VISUAL_SPEC[script];
    return (s && s.lines && s.lines[lineName]) || null;
}
// 多线型（sma/ema）：按线索引取调色板色 + 统一 kind/width
export function multiVisual(script, idx) {
    const s = VISUAL_SPEC[script];
    if (!s || !s.multi) return null;
    const pal = s.palette || MA_PALETTE;
    return { kind: s.kind || 'line', color: pal[idx % pal.length], width: s.width || 1 };
}
export function specFills(script) {
    const s = VISUAL_SPEC[script];
    return (s && s.fills) || null;
}
export function isMultiSpec(script) {
    const s = VISUAL_SPEC[script];
    return !!(s && s.multi);
}

// ---- 生效样式求解（渲染与设置弹窗共用同一函数 ⇒ 弹窗初值 ≡ 图上实际色） ----
// 优先级：实例 override(lines_style) > 视觉规格 > 脚本 style > 默认
export function effectiveStyle(script, lineName, scriptStyle, override, idx, scriptType) {
    const spec = VISUAL_SPEC[script];
    const lv = (spec && spec.lines && spec.lines[lineName])
        || (spec && spec.multi ? multiVisual(script, idx || 0) : null)
        || {};
    const sc = scriptStyle || {}, ov = override || {};
    // kind：中间层规格 > 脚本 line.type（blob/自定义的 histogram 等）> line.style.type > line
    const kind = lv.kind || scriptType || sc.type || 'line';
    const inks = { ...(lv.inks || {}), ...(ov.inks || {}) };
    return {
        kind,
        isHist: (kind === 'histogram' || kind === 'columns' || kind === 'bar'),
        color: ov.color || lv.color || sc.color || N.INFO,
        lineWidth: ov.lineWidth || lv.width || sc.lineWidth || 1,
        lineStyle: (ov.lineStyle != null ? ov.lineStyle
            : (lv.lineStyle != null ? lv.lineStyle : sc.lineStyle)) ?? 0,
        autoColor: (lv.autoColor !== false) && (sc.autoColor !== false) && (ov.autoColor !== false),
        inks,
        hasInks: !!(lv.inks && Object.keys(lv.inks).length),
        // 用户显式改过单色（且没改 inks）⇒ 停用逐点色策略，尊重用户挑的纯色
        flat: !!(ov.color && !ov.inks),
    };
}

// 填充带生效色：override（面板/AI）> follow 派生（跟随锚线色 + 原生透明度）> 规格静态色
export function effectiveFill(script, fill, resolvedLineColor, override) {
    const ov = override || {};
    if (ov.color) return ov.color;                       // 已含 alpha（8 位 hex / rgba）则原样用
    if (fill.follow && resolvedLineColor) {
        return transp(resolvedLineColor, ov.transparency != null ? ov.transparency
            : (fill.transparency != null ? fill.transparency : 92));
    }
    return fill.color || transp(N.INFO, 92);
}
