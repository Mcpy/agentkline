// 从 vendored Vela bundle 的运行时注册表生成画线工具规格（MCP 清单 + 服务端校验共用）。
// 用法: node tools/gen_drawing_spec.mjs   → agentkline/resources/drawing_spec.json
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(root, 'tools/vela-regression/package/dist');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'tools/vela-regression/package/package.json'), 'utf8'));
const src = fs.readFileSync(path.join(dist, 'vela.global.js'), 'utf8');

const noop = () => {};
const mk = () => new Proxy(function () {}, {
    get(t, k) { if (k === 'style') return new Proxy({}, { get: () => '', set: () => true });
        if (k === 'classList') return { add: noop, remove: noop, toggle: noop };
        if (k === 'getContext') return () => null; if (k === 'children') return [];
        if (k === 'getBoundingClientRect') return () => ({ left: 0, top: 0, width: 1, height: 1 });
        return undefined; },
    set() { return true; }, apply() { return mk(); },
});
const doc = { createElement: mk, createElementNS: mk, documentElement: mk(), body: mk(), head: mk(),
    addEventListener: noop, removeEventListener: noop, querySelector: () => null, querySelectorAll: () => [] };
const win = { document: doc, navigator: { userAgent: 'node' }, addEventListener: noop, removeEventListener: noop,
    requestAnimationFrame: () => 0, cancelAnimationFrame: noop,
    ResizeObserver: class { observe() {} disconnect() {} },
    matchMedia: () => ({ matches: false, addEventListener: noop }) };
const def = (k, v) => { try { Object.defineProperty(globalThis, k, { value: v, configurable: true, writable: true }); } catch (e) {} };
def('window', win); def('document', doc); def('requestAnimationFrame', win.requestAnimationFrame);
def('cancelAnimationFrame', noop); def('ResizeObserver', win.ResizeObserver); def('matchMedia', win.matchMedia);
(0, eval)(src);
const V = globalThis.Vela;
if (!V) throw new Error('Vela not found');

const short = { 'lines-channels-pitchforks': 'lines', 'fibonacci-gann': 'fibonacci',
    'patterns-waves-harmonics': 'patterns', measurements: 'measurements',
    'brushes-arrows-shapes': 'shapes', text: 'text', icons: 'icons' };

const metaByType = {};
for (const m of V.drawingTypes()) {
    let anchors = { min: 0, max: 0, slots: [] }, placement = 'click';
    try {
        const d = m.create({ paneId: 'price' });
        const s = d.anchorSchema();
        anchors = { min: s.min, max: s.max, slots: (s.slots || []).map(x => x.role) };
        placement = d.placementMode();
    } catch (e) { /* keep defaults */ }
    metaByType[m.type] = { type: m.type, label: m.label, anchors, placement,
        covers: !!m.coversSeries, hint: m.placementHint || '' };
}

const tb = V.defaultToolbar();
const groups = tb.groups.map(g => ({
    id: short[g.id] || g.id,
    label: g.label,
    sections: (g.sections || []).map(s => ({ label: s.label, tools: s.tools.map(t => t.type) })),
    tools: g.tools.map(t => t.type),
}));

const tools = [];
for (const g of groups) {
    for (const sec of g.sections) {
        for (const type of sec.tools) {
            const m = metaByType[type];
            if (m) tools.push({ ...m, group: g.id, section: sec.label });
        }
    }
}

const out = { vela: pkg.version, source: 'tools/vela-regression/package/dist/vela.global.js',
    generatedAt: new Date().toISOString().slice(0, 10), groups, tools };
const dest = path.join(root, 'agentkline/resources/drawing_spec.json');
fs.writeFileSync(dest, JSON.stringify(out, null, 1) + '\n');
console.log('wrote', dest, 'tools=', tools.length, 'groups=', groups.length, 'vela=', pkg.version);
