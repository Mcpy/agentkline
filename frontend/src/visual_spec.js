// ============================================================================
// 中间层视觉权威（P2 视觉层收归 + V1 原生保真调色 + v0.5.3 全量指标）
// ----------------------------------------------------------------------------
// 原则：指标脚本只出「纯计算值 + 语义线名」，一切视觉（kind/颜色/线宽/填充带/圆点）
// 由本表定义。未列入的脚本（custom 自定义）回退到其自带 lines[].style/type。
//
// 结构：
//   GENERATED_SPEC（indicator_visuals.js，tools/gen_indicator_visuals.mjs 生成）
//     = 74 个 Vela 经典研究的原生默认：线色/线宽/kind/填充带/水平线/区带/
//       以及从原生逐点色反推出的 colorRule（sign/slope/close/mid/momentum/absSlope）。
//   MANUAL（本文件）= 需要手写策略的特例（rsi 渐变、macd 动能四态、sar 圆点、kdj 扩展）。
//   合并规则：MANUAL 覆盖 GENERATED 的同名字段；lines 按线名逐条覆盖。
//
// 字段：
//   lines[线名] = { kind, color, width, lineStyle, autoColor, inks, pointColor, colorRule }
//     kind: 'line'|'area'|'histogram'|'columns'|'circles'|'cross'|'step'（缺省 line）
//     inks: {槽名: 色}  多色语义槽（sar 涨跌 / macd 柱四态 / rsi 渐变三段）
//     pointColor(v, ctx) → 色|null   逐点色策略；ctx={i,prev,close,params,ink,autoColor}
//     colorRule: 生成规则名（_colorRuleInk 解释），pointColor 缺席时生效
//   fills = [{ key, from:线名, to:线名, color, follow:线名, transparency }]
//   axis = { top, bottom }                       副图值域（隐藏 anchor series 撑出）
//   thresholds = { 名: 默认值 | (params)=>值 }    语义阈值（rsi 超买/超卖/中值）
//   levels = [{ key, at, color, lineStyle, title }]  水平线 → NativeIndicatorOutput.priceLines
//   zones  = [{ key, from, to, color }]              区带填充（from/to=阈值名或数值）
//
// 优先级（_lineSpec / effectiveStyle 内）：实例 override(lines_style) > 本规格 > 脚本 style > 默认。
// ============================================================================
import { GENERATED_SPEC } from './indicator_visuals.js';

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

// ---------------------------------------------------------------------------
// 手写特例（覆盖生成基线）
// ---------------------------------------------------------------------------
const MANUAL = {
    // RSI：单线（副图）——原生宽 2，中值 NEUTRAL 向超卖 BULLISH / 超买 BEARISH 渐变；
    //   70/50/30 水平线 + 超买/超卖区带 + 中带，值域 0..100（原生 boundedOscillator 同构）。
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
    // MACD：DIF/DEA 线 + 动能四态柱（副图）——MACD线=INFO、信号线=WARNING、柱=columns、零轴虚线
    'indicator/macd': {
        lines: {
            Histogram: {
                kind: 'columns', color: N.BULLISH, autoColor: true,
                inks: {
                    growAbove: N.BULLISH, fallAbove: transp(N.BULLISH, 50),
                    growBelow: transp(N.BEARISH, 50), fallBelow: N.BEARISH,
                },
                pointColor: (v, ctx) => (ctx.autoColor ? momentumInk(v, ctx.prev, ctx.ink) : null),
            },
            MACD: { kind: 'line', color: N.INFO, width: 1 },
            Signal: { kind: 'line', color: N.WARNING, width: 1 },
        },
        levels: [{ key: 'zero', at: 0, color: N.NEUTRAL, lineStyle: 'dashed', title: 'Zero Line' }],
    },
    // 抛物线转向：圆点画在蜡烛上下——原生逐点 close>=SAR 为涨绿、否则跌红
    'indicator/parabolic_sar': {
        lines: {
            SAR: {
                kind: 'circles', width: 2, color: N.BULLISH,
                inks: { bull: N.BULLISH, bear: N.BEARISH },
                pointColor: (v, ctx) => (ctx.close == null ? null : (ctx.close >= v ? ctx.ink.bull : ctx.ink.bear)),
            },
        },
    },
    // 线性回归：原生按拟合斜率给曲线红/绿（Curve 的逐 bar 差分∝斜率）；Slope 模式同色
    'indicator/linear_regression': {
        lines: {
            Curve: {
                kind: 'line', color: N.NEUTRAL, width: 2,
                inks: { up: N.BULLISH, down: N.BEARISH },
                pointColor: (v, ctx) => (ctx.prev == null ? null
                    : v > ctx.prev ? ctx.ink.up : v < ctx.prev ? ctx.ink.down : null),
            },
            Slope: {
                kind: 'line', color: N.NEUTRAL, width: 2,
                inks: { up: N.BULLISH, down: N.BEARISH },
                pointColor: (v, ctx) => (ctx.prev == null ? null
                    : v > ctx.prev ? ctx.ink.up : v < ctx.prev ? ctx.ink.down : null),
            },
        },
        levels: [{ key: 'zero', at: 0, color: N.NEUTRAL, lineStyle: 'dashed', title: 'Zero Line' }],
    },
    // PPO：柱=动能四态（原生 momentumColumnColors），PPO 线按零轴红绿（生成规则已覆盖）
    'indicator/ppo': {
        lines: {
            Histogram: {
                kind: 'columns', color: N.BULLISH, autoColor: true,
                inks: {
                    growAbove: N.BULLISH, fallAbove: transp(N.BULLISH, 70),
                    growBelow: transp(N.BEARISH, 70), fallBelow: N.BEARISH,
                },
                pointColor: (v, ctx) => (ctx.autoColor ? momentumInk(v, ctx.prev, ctx.ink) : null),
            },
        },
    },
    // TTM 挤压：Momentum 柱=动能四态；Squeeze State 有挤压=橙、无=灰
    'indicator/ttm_squeeze': {
        lines: {
            Momentum: {
                kind: 'columns', color: N.BULLISH, autoColor: true,
                inks: {
                    growAbove: transp(N.BULLISH, 60), fallAbove: transp(N.BULLISH, 60),
                    growBelow: transp(N.BEARISH, 60), fallBelow: transp(N.BEARISH, 60),
                },
                pointColor: (v, ctx) => (ctx.autoColor ? momentumInk(v, ctx.prev, ctx.ink) : null),
            },
            'Squeeze State': {
                kind: 'circles', color: N.NEUTRAL, width: 2,
                inks: { on: N.WARNING, off: N.NEUTRAL },
                pointColor: (v, ctx) => (v > 0 ? ctx.ink.on : ctx.ink.off),
            },
        },
    },
    // KDJ（产品扩展，无 Vela 原生）：对齐原生 stochastic（%K=INFO、%D=WARNING），J 取 JAW 紫
    'indicator/kdj': {
        lines: {
            K: { kind: 'line', color: N.INFO, width: 1 },
            D: { kind: 'line', color: N.WARNING, width: 1 },
            J: { kind: 'line', color: N.JAW, width: 1 },
        },
    },
};

function mergeSpec(base, over) {
    if (!over) return base || {};
    const out = { ...base, ...over };
    if (base && base.lines) out.lines = { ...base.lines, ...(over.lines || {}) };
    if (over.fills === undefined && base && base.fills) out.fills = base.fills;
    return out;
}

export const VISUAL_SPEC = {};
for (const key of new Set([...Object.keys(GENERATED_SPEC), ...Object.keys(MANUAL)])) {
    VISUAL_SPEC[key] = mergeSpec(GENERATED_SPEC[key], MANUAL[key]);
}

// 单线视觉规格查找（按线名）
export function visualSpec(script) { return VISUAL_SPEC[script] || null; }
export function lineVisual(script, lineName) {
    const s = VISUAL_SPEC[script];
    return (s && s.lines && s.lines[lineName]) || null;
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
    const lv = (spec && spec.lines
        && (spec.lines[lineName] || spec.lines[Object.keys(spec.lines)[0]])) || {};
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
