// 从 golden 生成指标视觉基线（v0.5.3）：线色/线宽/kind/填充带/水平线/区带。
// 用法: node tools/gen_indicator_visuals.mjs → frontend/src/indicator_visuals.js
// 手写特例（rsi/macd/sar/kdj 等）在 visual_spec.js 里覆盖本文件的条目。
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const golden = JSON.parse(fs.readFileSync(path.join(root, 'tools/indicator_port/golden.json'), 'utf8'));
const spec = JSON.parse(fs.readFileSync(path.join(root, 'agentkline/resources/indicator_spec.json'), 'utf8'));
const inputsOf = Object.fromEntries(spec.indicators.map(m => [m.type, m.inputs]));

const LS = { solid: 0, dotted: 1, dashed: 2 };
const closes = golden.bars.map(b => b.close);

// 从 golden 逐点色反推配色规则（原生 plot.colors）：规则 + 语义槽色。
// 只接受 100% 命中的简单规则；渐变/多段色（rsi 等）留给 visual_spec 手写。
function detectRule(values, colors) {
    const pts = [];
    for (let i = 0; i < values.length; i++) {
        if (values[i] != null && colors[i]) pts.push({ v: values[i], c: colors[i], i });
    }
    if (pts.length < 20) return null;
    const tryRule = (name, roles, roleOf) => {
        const sets = new Map(roles.map(r => [r, new Set()]));
        for (const p of pts) {
            const r = roleOf(p);
            if (!sets.has(r)) return null;
            sets.get(r).add(p.c);
        }
        const inks = {};
        for (const [r, set] of sets) {
            if (set.size > 1) return null;
            if (set.size === 1) inks[r] = [...set][0];
        }
        return Object.keys(inks).length >= 2 ? { colorRule: name, inks } : null;
    };
    const prev = (p) => (p.i > 0 ? values[p.i - 1] : null);
    return (
        tryRule('momentum', ['growAbove', 'fallAbove', 'growBelow', 'fallBelow'], p => {
            const q = prev(p);
            if (q == null) return 'none';
            return p.v >= 0 ? (p.v >= q ? 'growAbove' : 'fallAbove') : (p.v >= q ? 'growBelow' : 'fallBelow');
        })
        || tryRule('absSlope', ['grow', 'shrink'], p => {
            const q = prev(p);
            if (q == null) return 'none';
            return Math.abs(p.v) > Math.abs(q) ? 'grow' : 'shrink';
        })
        || tryRule('slope', ['up', 'down', 'flat'], p => {
            const q = prev(p);
            if (q == null) return 'none';
            return p.v > q ? 'up' : p.v < q ? 'down' : 'flat';
        })
        || tryRule('slope2', ['up', 'down'], p => {
            const q = prev(p);
            if (q == null) return 'none';
            return p.v >= q ? 'up' : 'down';
        })
        || (pts.filter(p => p.v >= -0.5 && p.v <= 1.5).length >= pts.length * 0.8
            ? tryRule('mid', ['above', 'below'], p => p.v >= 0.5 ? 'above' : 'below')
            : null)
        || tryRule('close', ['above', 'below'], p => closes[p.i] >= p.v ? 'above' : 'below')
        || tryRule('sign', ['pos', 'neg'], p => p.v >= 0 ? 'pos' : 'neg')
    );
}
const hidden = (p) => {
    const d = p.display || {};
    if (d && d.pane === false && d.legend === false && d.dataWindow === false) return true;
    const c = String(p.color || '');
    return c.length === 9 && c.endsWith('00');
};
const num = (x, d = 1) => (x == null ? d : x);

const out = {};
for (const [type, ref] of Object.entries(golden.results)) {
    if (type === 'kdj') continue;
    const byKey = Object.fromEntries(ref.plots.map(p => [p.key, p]));
    const visible = ref.plots.filter(p => !hidden(p));
    if (!visible.length && !ref.markers.length && !ref.polylines.length) continue;

    const entry = { lines: {} };
    for (const p of visible) {
        const line = {
            kind: p.kind || 'line',
            color: p.color || '#5b9cf6',
            width: num(p.width, 1),
        };
        if (p.lineStyle && LS[p.lineStyle] != null) line.lineStyle = LS[p.lineStyle];
        if (p.colors) {
            const rule = detectRule(p.values, p.colors);
            if (rule) Object.assign(line, rule);
        }
        entry.lines[p.title] = line;
    }

    // 填充带：两端都是可见线的才保留（anchor 型区带另走 zones）
    const fills = [];
    for (const b of ref.bands || []) {
        const from = byKey[b.from], to = byKey[b.to];
        if (!from || !to || hidden(from) || hidden(to)) continue;
        if (b.gradient) continue;                 // 逐点渐变不在 emit 契约内
        fills.push({ key: b.key, from: from.title, to: to.title, color: b.color });
    }
    if (fills.length) entry.fills = fills;

    // 阈值/水平线：level 价 == 某输入默认值 且标题对得上 → 绑定参数（可跟随设置变化）
    const inputs = inputsOf[type] || [];
    const thresholds = {};
    const levels = [];
    for (const l of ref.levels || []) {
        const name = String(l.title || l.key || '');
        const hit = inputs.find(i => (i.key || '').toLowerCase() === String(l.key).toLowerCase())
            || inputs.find(i => name.toLowerCase().includes(String(i.title || '').toLowerCase()) && i.defval === l.price);
        const at = hit ? hit.key : l.price;
        if (hit) thresholds[hit.key] = l.price;
        const lv = { key: l.key, at, title: l.title || l.key, color: l.color || '#787b86' };
        if (l.lineStyle && LS[l.lineStyle] != null) lv.lineStyle = LS[l.lineStyle];
        levels.push(lv);
    }
    if (levels.length) {
        entry.levels = levels;
        if (Object.keys(thresholds).length) entry.thresholds = thresholds;
    }

    // 区带：band 两端是隐藏 anchor → 取 anchor 常量值做数值区带；Top/Bottom 同时给 axis
    const zones = [];
    let axis = null;
    for (const b of ref.bands || []) {
        const from = byKey[b.from], to = byKey[b.to];
        if (!from || !to) continue;
        if (!hidden(from) && !hidden(to)) continue;
        if (b.gradient) continue;
        const val = (p) => {
            const v = (p.values || []).find(x => x != null);
            return v == null ? null : Number(v);
        };
        const a = val(from), z = val(to);
        if (a == null || z == null) continue;
        zones.push({ key: b.key, from: a, to: z, color: b.color });
        const title = `${from.title} ${to.title}`.toLowerCase();
        if (title.includes('top') || title.includes('bottom')) {
            const top = [a, z].find(v => v >= 50);
            const bottom = [a, z].find(v => v < 50);
            if (top != null && bottom != null) axis = { top, bottom };
        }
    }
    if (axis) entry.axis = axis;
    if (zones.length) entry.zones = zones;

    out['indicator/' + type.replace(/-/g, '_')] = entry;
}

const header = `// 由 tools/gen_indicator_visuals.mjs 从 Vela golden 生成（v0.5.3），请勿手改。
// 每项 = {lines, fills?, levels?, thresholds?, zones?, axis?}；visual_spec.js 的手写特例会覆盖同名条目。
`;
const body = 'export const GENERATED_SPEC = ' + JSON.stringify(out, null, 4) + ';\n';
fs.writeFileSync(path.join(root, 'frontend/src/indicator_visuals.js'), header + body);
console.log(`wrote frontend/src/indicator_visuals.js: ${Object.keys(out).length} entries`);
