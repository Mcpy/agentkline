// 从 vendored Vela bundle 生成内置指标目录（v0.5.3 全量移植）。
// 用法: node tools/gen_indicator_spec.mjs → agentkline/resources/indicator_spec.json
//
// 产出只含「可计算研究」：Vela 的 volume / vpvr 是 layer 型原生指标，不在此目录。
// 字段：
//   type      Vela 原生类型（连字符）
//   script    AgentKLine 脚本 id（indicator/<type 下划线>）
//   title/short/title_zh
//   group     7 个分类 id
//   overlay   true=主图叠加 / false=副图
//   inputs    [{key,title,type,defval,min,max,step,options}]（color 已剔除，视觉走 visual spec）
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(root, 'tools/vela-regression/package/dist');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'tools/vela-regression/package/package.json'), 'utf8'));
const src = fs.readFileSync(path.join(dist, 'vela.global.js'), 'utf8');

const noop = () => {};
const mk = () => new Proxy(function () {}, {
    get(t, k) {
        if (k === 'style') return new Proxy({}, { get: () => '', set: () => true });
        if (k === 'classList') return { add: noop, remove: noop, toggle: noop };
        if (k === 'getContext') return () => mk();
        if (k === 'children') return [];
        if (k === 'parentElement') return mk();
        if (k === 'getBoundingClientRect') return () => ({ left: 0, top: 0, width: 800, height: 600 });
        if (['appendChild', 'removeChild', 'setAttribute', 'addEventListener', 'setProperty'].includes(k)) return noop;
        return mk();
    },
    set() { return true; }, apply() { return mk(); },
});
const doc = { createElement: mk, createElementNS: mk, documentElement: mk(), body: mk(), head: mk(),
    addEventListener: noop, removeEventListener: noop, querySelector: () => mk(), querySelectorAll: () => [] };
const win = { document: doc, navigator: { userAgent: 'node' }, addEventListener: noop, removeEventListener: noop,
    requestAnimationFrame: () => 0, cancelAnimationFrame: noop,
    ResizeObserver: class { observe() {} disconnect() {} },
    matchMedia: () => ({ matches: false, addEventListener: noop }), devicePixelRatio: 1 };
const def = (k, v) => { try { Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true }); } catch (e) {} };
def('window', win); def('document', doc); def('requestAnimationFrame', win.requestAnimationFrame);
def('cancelAnimationFrame', noop); def('ResizeObserver', win.ResizeObserver); def('matchMedia', win.matchMedia);
(0, eval)(src);
const V = globalThis.Vela;
try { new V.Vela(mk(), { theme: 'dark' }); } catch (e) { /* 注册已发生，挂载失败无碍 */ }

const GROUPS = [
    { id: 'average', label: '均线', label_en: 'Averages' },
    { id: 'band', label: '通道/带状', label_en: 'Bands' },
    { id: 'oscillator', label: '震荡', label_en: 'Oscillators' },
    { id: 'trend', label: '趋势', label_en: 'Trend' },
    { id: 'volatility', label: '波动率', label_en: 'Volatility' },
    { id: 'volume', label: '成交量', label_en: 'Volume' },
    { id: 'overlay', label: '覆盖', label_en: 'Overlay' },
];

const GROUP_OF = {
    'sma': 'average', 'ema': 'average', 'moving-average': 'average', 'rma': 'average',
    'zlema': 'average', 'vidya': 'average', 'ma-envelope': 'average', 'linear-regression': 'average',
    'bollinger-bands': 'band', 'percent-b': 'band', 'bandwidth': 'band', 'keltner-channels': 'band',
    'donchian-channels': 'band', 'chandelier-exit': 'band', 'chande-kroll-stop': 'band',
    'supertrend': 'band', 'williams-alligator': 'band', 'gator-oscillator': 'band',
    'rsi': 'oscillator', 'stochastic': 'oscillator', 'stochastic-rsi': 'oscillator', 'macd': 'oscillator',
    'ppo': 'oscillator', 'awesome-oscillator': 'oscillator', 'commodity-channel-index': 'oscillator',
    'williams-percent-r': 'oscillator', 'chande-momentum-oscillator': 'oscillator', 'connors-rsi': 'oscillator',
    'fisher-transform': 'oscillator', 'trix': 'oscillator', 'true-strength-index': 'oscillator',
    'smi-ergodic': 'oscillator', 'schaff-trend-cycle': 'oscillator', 'know-sure-thing': 'oscillator',
    'coppock-curve': 'oscillator', 'detrended-price-oscillator': 'oscillator', 'rate-of-change': 'oscillator',
    'ultimate-oscillator': 'oscillator', 'relative-vigor-index': 'oscillator', 'relative-volatility-index': 'oscillator',
    'balance-of-power': 'oscillator', 'elder-ray': 'oscillator', 'ttm-squeeze': 'oscillator',
    'aroon': 'trend', 'average-directional-index': 'trend', 'vortex-indicator': 'trend',
    'average-true-range': 'volatility', 'historical-volatility': 'volatility', 'chaikin-volatility': 'volatility',
    'mass-index': 'volatility', 'standard-deviation': 'volatility', 'ulcer-index': 'volatility',
    'choppiness-index': 'volatility',
    'on-balance-volume': 'volume', 'accumulation-distribution': 'volume', 'chaikin-money-flow': 'volume',
    'chaikin-oscillator': 'volume', 'ease-of-movement': 'volume', 'force-index': 'volume',
    'klinger-oscillator': 'volume', 'money-flow-index': 'volume', 'negative-volume-index': 'volume',
    'positive-volume-index': 'volume', 'price-volume-trend': 'volume', 'volume-oscillator': 'volume',
    'pvo': 'volume', 'volume-flow-indicator': 'volume', 'intraday-intensity': 'volume',
    'parabolic-sar': 'overlay', 'vwap': 'overlay', 'pivot-points': 'overlay', '52-week-high-low': 'overlay',
    'zigzag': 'overlay', 'williams-fractal': 'overlay',
};

const ZH = {
    'sma': '简单移动平均', 'ema': '指数移动平均', 'moving-average': '移动平均（多类型）', 'rma': '平滑移动平均',
    'zlema': '零延迟 EMA', 'vidya': '可变指数动态平均', 'ma-envelope': '均线包络', 'linear-regression': '线性回归曲线',
    'bollinger-bands': '布林带', 'percent-b': '布林 %B', 'bandwidth': '布林带宽', 'keltner-channels': '肯特纳通道',
    'donchian-channels': '唐奇安通道', 'chandelier-exit': '吊灯止损', 'chande-kroll-stop': '钱德-克罗尔止损',
    'supertrend': '超级趋势', 'williams-alligator': '威廉鳄鱼线', 'gator-oscillator': '鳄鱼振荡器',
    'rsi': '相对强弱', 'stochastic': '随机指标', 'stochastic-rsi': '随机 RSI', 'macd': '指数异同移动平均',
    'ppo': '百分比价格振荡器', 'awesome-oscillator': '动量震荡器', 'commodity-channel-index': '顺势指标 CCI',
    'williams-percent-r': '威廉 %R', 'chande-momentum-oscillator': '钱德动量振荡器', 'connors-rsi': '康纳斯 RSI',
    'fisher-transform': '费雪变换', 'trix': '三重指数平滑', 'true-strength-index': '真实强度指数',
    'smi-ergodic': 'SMI 遍历', 'schaff-trend-cycle': '沙夫趋势周期', 'know-sure-thing': '明确趋势 KST',
    'coppock-curve': '科波克曲线', 'detrended-price-oscillator': '去趋势价格振荡器', 'rate-of-change': '变动率 ROC',
    'ultimate-oscillator': '终极振荡器', 'relative-vigor-index': '相对活力指数', 'relative-volatility-index': '相对波动率指数',
    'balance-of-power': '力量平衡', 'elder-ray': '埃尔德射线', 'ttm-squeeze': 'TTM 挤压',
    'aroon': '阿隆', 'average-directional-index': '平均趋向指数 ADX', 'vortex-indicator': '涡流指标',
    'average-true-range': '平均真实波幅 ATR', 'historical-volatility': '历史波动率', 'chaikin-volatility': '蔡金波动率',
    'mass-index': '质量指数', 'standard-deviation': '标准差', 'ulcer-index': '溃疡指数', 'choppiness-index': '震荡指数',
    'on-balance-volume': '能量潮 OBV', 'accumulation-distribution': '累积/派发线', 'chaikin-money-flow': '蔡金资金流',
    'chaikin-oscillator': '蔡金振荡器', 'ease-of-movement': '简易波动', 'force-index': '力度指数',
    'klinger-oscillator': '克林格振荡器', 'money-flow-index': '资金流量指数 MFI', 'negative-volume-index': '负量指数',
    'positive-volume-index': '正量指数', 'price-volume-trend': '价量趋势', 'volume-oscillator': '成交量振荡器',
    'pvo': '百分比成交量振荡器', 'volume-flow-indicator': '成交量流量指标', 'intraday-intensity': '日内强度',
    'parabolic-sar': '抛物线转向 SAR', 'vwap': '成交量加权均价', 'pivot-points': '枢轴点',
    '52-week-high-low': '52 周高低点', 'zigzag': '之字转向', 'williams-fractal': '威廉分形',
};

const scriptOf = (type) => 'indicator/' + type.replace(/-/g, '_');

const indicators = [];
for (const type of V.nativeIndicatorTypes()) {
    if (!GROUP_OF[type]) continue;                     // volume / vpvr
    const d = V.getNativeIndicator(type);
    const schema = d.inputsSchema ? d.inputsSchema() : [];
    const inputs = schema
        .filter(i => i.type !== 'color' && i.group !== 'Style')
        .map(i => {
            const o = { key: i.key, title: i.title, type: i.type, defval: i.defval };
            if (i.min != null) o.min = i.min;
            if (i.max != null) o.max = i.max;
            if (i.step != null) o.step = i.step;
            if (Array.isArray(i.options)) o.options = i.options.slice();
            return o;
        });
    // linear-regression 默认 Curve 实际叠在主图（Vela 的 plot.overlay），故按主图归类；
    //   Slope 模式在主图上会退化（已知，见 v0.5.3 文档）。
    const overlay = type === 'linear-regression' ? true : !!d.overlay;
    indicators.push({
        type,
        script: scriptOf(type),
        title: d.title,
        short: d.shortTitle || d.title,
        title_zh: ZH[type] || d.title,
        group: GROUP_OF[type],
        overlay,
        inputs,
    });
}
// 产品扩展：KDJ（无 Vela 原生对应，对齐 stochastic 视觉；保留）
indicators.push({
    type: 'kdj',
    script: 'indicator/kdj',
    title: 'Stochastic KDJ',
    short: 'KDJ',
    title_zh: '随机指标 KDJ（扩展）',
    group: 'oscillator',
    overlay: false,
    inputs: [{ key: 'n', title: 'Length', type: 'int', defval: 9, min: 1, max: 500, step: 1 }],
});

const order = new Map(GROUPS.map((g, i) => [g.id, i]));
indicators.sort((a, b) => order.get(a.group) - order.get(b.group));

const spec = {
    vela: pkg.version,
    generated_by: 'tools/gen_indicator_spec.mjs',
    groups: GROUPS,
    indicators,
};
const out = path.join(root, 'agentkline/resources/indicator_spec.json');
fs.writeFileSync(out, JSON.stringify(spec, null, 2) + '\n');
console.log(`wrote ${out}: ${indicators.length} indicators, ${GROUPS.length} groups (vela ${pkg.version})`);
