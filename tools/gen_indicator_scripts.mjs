// 生成内置指标脚本 wrapper（v0.5.3 全量移植）。
// 用法: node tools/gen_indicator_scripts.mjs
// 读 agentkline/resources/indicator_spec.json → 写 agentkline/resources/scripts/indicator/<stem>.py
// 脚本只做三件事：字面量元数据（NAME/DESC/PARAMS/SUBPLOT）+ 调用 Python 单源注册表。
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const spec = JSON.parse(fs.readFileSync(path.join(root, 'agentkline/resources/indicator_spec.json'), 'utf8'));
const outDir = path.join(root, 'agentkline/resources/scripts/indicator');

const py = (v) => {
    if (v === true) return 'True';
    if (v === false) return 'False';
    if (v === null) return 'None';
    if (typeof v === 'string') return JSON.stringify(v);
    if (typeof v === 'number') return String(v);
    if (Array.isArray(v)) return '[' + v.map(py).join(', ') + ']';
    if (typeof v === 'object') return '{' + Object.entries(v).map(([k, x]) => `${JSON.stringify(k)}: ${py(x)}`).join(', ') + '}';
    throw new Error('unsupported ' + v);
};

const existing = new Set(spec.indicators.map(m => m.script.split('/').pop() + '.py'));
// 旧版 8 个里被 Vela 研究取代的三个：删除（无兼容别名）
for (const stale of ['bb.py', 'sar.py', 'obv.py']) {
    const p = path.join(outDir, stale);
    if (fs.existsSync(p)) { fs.unlinkSync(p); console.log('removed', stale); }
}

for (const meta of spec.indicators) {
    if (meta.type === 'kdj') continue;              // KDJ 是产品扩展，手写脚本保留
    const stem = meta.script.split('/').pop();
    const params = {};
    for (const inp of meta.inputs) params[inp.key] = inp.defval;
    const desc = `${meta.title_zh} — ${meta.title}（Vela 内置研究移植，值由 Python 单源计算）`;
    const body = `"""${desc}

由 tools/gen_indicator_scripts.mjs 生成，请勿手改；改计算去 agentkline/indicators/。
"""
from agentkline.indicators.registry import run

TYPE = ${py(meta.type)}
NAME = ${py(meta.short)}
DESC = ${py(desc)}
PARAMS = ${py(params)}
SUBPLOT = ${meta.overlay ? 'False' : 'True'}


def main(params, ohlcv):
    return run(TYPE, params, ohlcv)
`;
    fs.writeFileSync(path.join(outDir, `${stem}.py`), body);
}
console.log(`wrote ${spec.indicators.length - 1} indicator wrappers to ${outDir}`);
