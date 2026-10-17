// Vela 原生指标映射（重构 Phase A —— 用 Vela 内置指标的实现方式：图表内从 bar store 同步计算）
// 与 Vela 冲突的旧设计（后端算值 + WS 推 frontend + 自定义 native 类型 emit）在映射命中时一律让位。
// 未映射的脚本（kdj/tenp 等自定义）仍走旧通道作为回退。

export const NATIVE_MAP = {
    'indicator/bb':   { type: 'bollinger-bands',   inputs: p => ({ length: p.period ?? 20, mult: p.std ?? 2 }) },
    'indicator/rsi':  { type: 'rsi',               inputs: p => ({ length: p.period ?? 14 }) },
    'indicator/macd': { type: 'macd',              inputs: p => ({ fastLength: p.fast ?? 12, slowLength: p.slow ?? 26, signalLength: p.signal ?? 9 }) },
    'indicator/obv':  { type: 'on-balance-volume', inputs: () => ({}) },
    'indicator/sar':  { type: 'parabolic-sar',     inputs: p => ({ start: p.af_step ?? 0.02, increment: p.af_step ?? 0.02, maximum: p.af_max ?? 0.2 }) },
};

// sma/ema 为「每周期一个实例」的多实例内置指标（native 侧一个 type，多实例化）
export function nativeMulti(script) {
    if (script === 'indicator/sma') return 'sma';
    if (script === 'indicator/ema') return 'ema';
    return null;
}

export function nativeTypeOf(script) {
    const m = NATIVE_MAP[script];
    if (m) return m.type;
    return nativeMulti(script);
}

// 原生自带 pane 的副图名（振荡器）：消息序无关的守卫——subplot_create 可能先于 indicator_add 到达
export const NATIVE_SUBPLOTS = new Set(
    Object.entries(NATIVE_MAP)
        .filter(([, m]) => /rsi|macd|obv|stochastic|atr|adx|cci|vwap/i.test(m.type))
        .map(([script]) => script.split('/').pop())
);
export function isNativeSubplot(name) { return NATIVE_SUBPLOTS.has(name); }

// ---- 样式 → Vela 原生输入项（Phase A-6）----
// Vela 原生把颜色/线型做成 indicator **输入项**（P()=color、lineStyle 选择）；
// 线宽仅少数指标暴露（bb/rsi/macd 本 build 无）→ 仅映射存在的能力。
const MAIN_COLOR_KEY = {
    'indicator/bb': 'color', 'indicator/rsi': 'color', 'indicator/macd': 'color',
    'indicator/obv': 'color', 'indicator/sar': 'bullColor',
    'indicator/sma': 'color', 'indicator/ema': 'color',
};
const LINE_STYLE_STR = { 0: 'solid', 1: 'dotted', 2: 'dashed' };
// 实测（80 根放大截图对照，字符串/整数两种取值均试）：bb 的 lineStyle 输入项存在且取值被接受，
// 但渲染层仍画实线 → 判定本 build 未生效，控件按无用隐藏（Vela 侧能力/未接线）。
const HAS_LINESTYLE = new Set([]);

export function styleInputs(script, style, linesStyle) {
    const out = {};
    const st = style || {};
    const key = MAIN_COLOR_KEY[script];
    if (key && st.color) out[key] = st.color;
    if (st.lineStyle != null && HAS_LINESTYLE.has(script)) out.lineStyle = LINE_STYLE_STR[st.lineStyle] || 'solid';
    if (st.lineWidth != null && HAS_LINESTYLE.has(script) && false) out.lineWidth = st.lineWidth;  // 本 build 无此输入
    return out;
}
// 多线样式：我们的线名 → 原生输入键（bb 中轨 basisColor；macd 信号线 signalColor）
const LINE_COLOR_KEY = {
    'indicator/bb': { 'BB_UPPER': 'color', 'BB_LOWER': 'color', 'BB_MID': 'basisColor' },
    'indicator/macd': { 'DIF': 'color', 'DEA': 'signalColor', 'MACD': 'growAboveColor' },
};
export function lineStyleInputs(script, linesStyle) {
    const map = LINE_COLOR_KEY[script];
    const out = {};
    if (!map || !linesStyle) return out;
    Object.entries(linesStyle).forEach(([name, ls]) => {
        const k = map[name];
        if (!k || !ls) return;
        if (ls.color) out[k] = ls.color;
        if (ls.lineStyle != null && HAS_LINESTYLE.has(script)) out.lineStyle = LINE_STYLE_STR[ls.lineStyle] || 'solid';
    });
    return out;
}
export function supportsNativeStyle(script) { return !!MAIN_COLOR_KEY[script]; }
// 线名 → 原生色键（弹窗初值/多线样式共用）
export function lineColorKey(script, lineName) {
    const m = LINE_COLOR_KEY[script];
    if (m && m[lineName]) return m[lineName];
    return MAIN_COLOR_KEY[script] || null;
}
// 设置弹窗用：本 build 下该指标原生支持的样式能力（避免给出无效控件）
export function nativeStyleCaps(script) {
    return {
        color: !!MAIN_COLOR_KEY[script],
        lineStyle: HAS_LINESTYLE.has(script),
        width: false,   // 本 build 映射的指标均无 lineWidth 输入（Vela 仅个别指标暴露）
    };
}
