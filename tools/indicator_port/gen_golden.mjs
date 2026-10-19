// 生成 v0.5.3 指标移植的 golden 参考（开发期工具，产物 gitignore）。
// 用法: node tools/indicator_port/gen_golden.mjs
// 输出: tools/indicator_port/golden.json
//   fixture 固定 400 根小时线（确定性伪随机），每个 Vela 经典指标用默认输入跑 spec.compute，
//   记录 plots/values/bands/levels/markers/polylines；Python 端口逐值对齐（见 compare.py）。
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const dist = path.join(root, 'tools/vela-regression/package/dist');
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
try { new V.Vela(mk(), { theme: 'dark' }); } catch (e) {}

// 确定性行情：趋势 + 噪声，高低温量都非平坦（避免指标退化）
let seed = 42;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const bars = [];
let price = 100;
const start = 1700000000000;
for (let i = 0; i < 400; i++) {
    const o = price;
    const drift = Math.sin(i / 37) * 0.35;
    price = Math.max(1, o + drift + (rnd() - 0.5) * 2);
    const h = Math.max(o, price) + rnd() * 0.8;
    const l = Math.min(o, price) - rnd() * 0.8;
    bars.push({
        time: start + i * 3600000,
        open: +o.toFixed(4), high: +h.toFixed(4), low: +l.toFixed(4), close: +price.toFixed(4),
        volume: Math.round(1000 + rnd() * 5000),
    });
}

const spec = JSON.parse(fs.readFileSync(path.join(root, 'agentkline/resources/indicator_spec.json'), 'utf8'));
const results = {};
for (const meta of spec.indicators) {
    if (meta.type === 'kdj') continue;                 // 产品扩展，无 Vela golden
    const d = V.getNativeIndicator(meta.type);
    const inst = d.create();
    const inputs = d.defaultInputs();
    const r = inst.spec.compute(bars, inputs);
    const plots = (r.plots || []).map(p => {
        const plot = {
            key: p.key, title: p.title, kind: p.kind || 'line',
            color: p.color, width: p.width ?? null, lineStyle: p.lineStyle ?? null,
            base: p.base ?? null, display: p.display ?? null,
            values: p.values,
        };
        if (p.colors) plot.colors = p.colors;
        return plot;
    });
    results[meta.type] = {
        inputs,
        plots,
        bands: (r.bands || []).map(b => ({ ...b })),
        levels: (r.levels || []).map(l => ({ ...l })),
        markers: (r.markers || []).map(m => ({ ...m })),
        polylines: (r.polylines || []).map(p => ({ ...p })),
    };
}

const out = { vela: spec.vela, fixture: { start, count: bars.length }, bars, results };
const file = path.join(root, 'tools/indicator_port/golden.json');
fs.writeFileSync(file, JSON.stringify(out));
console.log(`wrote ${file}: ${Object.keys(results).length} types, ${(fs.statSync(file).size / 1024 / 1024).toFixed(2)} MB`);
for (const [t, r] of Object.entries(results)) {
    const hidden = r.plots.filter(p => p.color && String(p.color).endsWith('00')).length;
    console.log(`${t.padEnd(28)} plots=${r.plots.length}${hidden ? ` (anchor ${hidden})` : ''} bands=${r.bands.length} levels=${r.levels.length} markers=${r.markers.length} polylines=${r.polylines.length}`);
}
