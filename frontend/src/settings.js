import { state } from './state.js';
import { log } from './log.js';

// ============================================================
// 指标设置弹窗：显示名 / 参数 / 颜色 / 线宽 / 线型
// ============================================================
const LINE_STYLES = [[0, '实线'], [1, '点线'], [2, '虚线']];

function post(name, payload) {
    return fetch(`/api/indicator/${encodeURIComponent(name)}`, {   // v0.4.1: flat body 约定
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, board_id: state.currentBoard, timeframe: state.currentTimeframe }),
    }).then(r => r.json());
}

function row(html) {
    const d = document.createElement('div');
    d.className = 'set-row';
    d.innerHTML = html;
    return d;
}

export async function openSettings(name) {
    const ind = state.indicators[name];
    if (!ind) return;

    // 清理旧弹窗
    document.querySelectorAll('.set-modal').forEach(e => e.remove());

    const modal = document.createElement('div');
    modal.className = 'set-modal';
    const panel = document.createElement('div');
    panel.className = 'set-panel';
    modal.appendChild(panel);

    const title = document.createElement('div');
    title.className = 'set-title';
    title.textContent = `指标设置 · ${ind.display_name || name}`;
    panel.appendChild(title);

    // ---- 显示名 ----
    panel.appendChild(row(`<label>显示名</label>`));
    const nameRow = row('');
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = ind.display_name || '';
    nameInput.placeholder = name;
    const autoBtn = document.createElement('button');
    autoBtn.className = 'set-btn';
    autoBtn.textContent = '恢复自动';
    autoBtn.title = '按 根名(参数) 自动命名';
    let wantAuto = false;
    autoBtn.onclick = () => { wantAuto = true; nameInput.value = ''; nameInput.placeholder = '(自动)'; };
    nameRow.appendChild(nameInput);
    nameRow.appendChild(autoBtn);
    panel.appendChild(nameRow);

    // ---- 参数（v0.4.3：脚本 PARAMS meta 兜底合并，旧空参实例也有得改；list 参=逗号文本） ----
    let metaParams = {};
    try {
        const sr = await fetch('/api/scripts');
        const sd = await sr.json();
        const list = sd.scripts || sd || [];
        const me = list.find(x => x.id === ind.script);
        metaParams = (me && me.params) || {};
    } catch (e) { /* meta 拿不到就用实例参数 */ }
    const params = { ...metaParams, ...(ind.params || {}) };
    const paramInputs = {};
    if (Object.keys(params).length) {
        panel.appendChild(row(`<label>参数</label>`));
        const grid = document.createElement('div');
        grid.className = 'set-grid';  // 双列网格，参数多时不撑高弹窗
        Object.entries(params).forEach(([k, v]) => {
            const r = row('');
            const lab = document.createElement('span');
            lab.className = 'set-key';
            lab.textContent = k;
            const inp = document.createElement('input');
            if (Array.isArray(v)) {
                inp.type = 'text';
                inp.value = v.join(',');
                inp.title = '逗号分隔列表';
                inp.dataset.list = '1';
            } else {
                inp.type = 'number';
                inp.step = 'any';
                inp.value = v;
            }
            paramInputs[k] = inp;
            r.appendChild(lab); r.appendChild(inp);
            grid.appendChild(r);
        });
        panel.appendChild(grid);
    }

    // ---- 样式 ----
    const isMulti = Array.isArray(ind.lines) && ind.lines.length > 0;
    const styleInputs = [];  // {getKey, color, width, style}
    panel.appendChild(row(`<label>样式</label>`));
    const mkStyle = (getCur, keyLabel, isHist) => {
        const cur = getCur() || {};
        const r = row('');
        if (keyLabel) { const s = document.createElement('span'); s.className = 'set-key'; s.textContent = keyLabel; r.appendChild(s); }
        const color = document.createElement('input');
        color.type = 'color';
        color.value = toHex(cur.color || '#4fc3f7');
        const hint = (t) => { const s = document.createElement('span'); s.className = 'set-hint'; s.textContent = t; return s; };
        let auto = null, width = null, lstyle = null;
        if (isHist) {
            // 柱状图：仅「自动红绿」+ 柱颜色（无粗细/线型）
            auto = document.createElement('input');
            auto.type = 'checkbox';
            auto.checked = cur.autoColor !== false;
            auto.title = '涨跌自动红绿';
            const sync = () => { color.disabled = auto.checked; };
            auto.onchange = sync; sync();
            r.appendChild(auto); r.appendChild(hint('自动红绿'));
            r.appendChild(hint('柱颜色'));
        } else {
            width = document.createElement('input');
            width.type = 'number'; width.min = '1'; width.max = '6'; width.value = cur.lineWidth || 2; width.style.width = '46px';
            lstyle = document.createElement('select');
            LINE_STYLES.forEach(([v, t]) => { const o = document.createElement('option'); o.value = v; o.textContent = t; lstyle.appendChild(o); });
            lstyle.value = String(cur.lineStyle ?? 0);
            r.appendChild(hint('颜色'));
        }
        r.appendChild(color);
        if (width) { r.appendChild(hint('粗细')); r.appendChild(width); }
        if (lstyle) { r.appendChild(hint('样式')); r.appendChild(lstyle); }
        panel.appendChild(r);
        return { color, width, lstyle, auto, isHist };
    };
    if (isMulti) {
        ind.lines.forEach(ln => {
            const isHist = (ln.type === 'histogram' || ln.type === 'bar');
            styleInputs.push({ line: ln.name, ...mkStyle(() => ln.style, ln.name, isHist) });
        });
    } else {
        const isHist = (ind.type === 'histogram' || ind.type === 'bar');
        styleInputs.push({ line: null, ...mkStyle(() => ind.style, null, isHist) });
    }

    // ---- 按钮 ----
    const foot = row('');
    foot.className = 'set-foot';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'set-btn primary';
    saveBtn.textContent = '保存';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'set-btn';
    cancelBtn.textContent = '取消';
    foot.appendChild(saveBtn); foot.appendChild(cancelBtn);
    panel.appendChild(foot);

    cancelBtn.onclick = () => modal.remove();
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

    saveBtn.onclick = async () => {
        try {
            // 1) 参数 + 命名
            const p1 = {};
            const newParams = {};
            let paramsChanged = false;
            Object.entries(paramInputs).forEach(([k, inp]) => {
                if (inp.dataset.list) {
                    newParams[k] = inp.value.split(',').map(x => x.trim()).filter(x => x !== '')
                        .map(x => (isNaN(parseFloat(x)) ? x : parseFloat(x)));
                } else {
                    const nv = parseFloat(inp.value);
                    newParams[k] = isNaN(nv) ? inp.value : nv;
                }
                if (JSON.stringify(newParams[k]) !== JSON.stringify(params[k])) paramsChanged = true;
            });
            if (paramsChanged) p1.params = newParams;
            if (wantAuto) p1.auto_label = true;
            else if (nameInput.value && nameInput.value !== ind.display_name) p1.display_name = nameInput.value;
            if (Object.keys(p1).length) await post(name, p1);

            // 2) 样式
            const p2 = {};
            const stylePayload = (si, base) => {
                if (si.isHist) {
                    // 柱状图：只发 autoColor + 颜色（保留原 lineWidth）；勾选=自动红绿
                    return { ...base, autoColor: !!(si.auto && si.auto.checked), color: si.color.value };
                }
                return { ...base, color: si.color.value, lineWidth: parseInt(si.width.value) || 2, lineStyle: parseInt(si.lstyle.value) || 0 };
            };
            if (isMulti) {
                const ls = {};
                styleInputs.forEach(si => { ls[si.line] = stylePayload(si, {}); });
                p2.lines_style = ls;
            } else {
                p2.style = stylePayload(styleInputs[0], (ind.style || {}));
            }
            await post(name, p2);

            log('info', `指标更新: ${name}`);
            modal.remove();
        } catch (e) {
            log('error', `指标更新失败: ${e}`);
        }
    };

    document.body.appendChild(modal);
}

function toHex(c) {
    if (!c) return '#4fc3f7';
    if (c.startsWith('#') && c.length === 7) return c;
    if (c.startsWith('#') && c.length === 4) return '#' + [...c.slice(1)].map(x => x + x).join('');
    return '#4fc3f7';
}
