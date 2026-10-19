import { t } from './i18n.js';
import { state } from './state.js';
import { log } from './log.js';

// ============================================================
// 指标设置弹窗：显示名 / 参数 / 颜色 / 线宽 / 线型
// ============================================================
const LINE_STYLES = [[0, t('set.solid')], [1, t('set.dotted')], [2, t('set.dashed')]];
// V1：中间层视觉规格（原生保真色）——弹窗初值与图上实际色同源，避免「面板显示 ≠ 画面」
import { effectiveStyle, effectiveFill, specFills, visualSpec, transp } from './visual_spec.js';

// 逐点色语义槽标签（sar 涨/跌、rsi 低/中/高）；非白名单槽名直接显示原名
const INK_KEYS = new Set(['bull', 'bear', 'low', 'mid', 'high']);
function inkLabel(k) { return INK_KEYS.has(k) ? t('set.ink_' + k) : k; }

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
    title.textContent = t('set.title', {name: ind.display_name || name});
    panel.appendChild(title);

    // ---- 显示名 ----
    panel.appendChild(row(`<div class="set-sec">${t('set.sec_name')}</div>`));
    const nameRow = row('');
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = ind.display_name || '';
    nameInput.placeholder = name;
    const autoBtn = document.createElement('button');
    autoBtn.className = 'set-btn';
    autoBtn.textContent = t('set.auto_btn');
    autoBtn.title = t('set.auto_title');
    let wantAuto = false;
    autoBtn.onclick = () => { wantAuto = true; nameInput.value = ''; nameInput.placeholder = t('set.auto_suffix'); };
    nameRow.appendChild(nameInput);
    nameRow.appendChild(autoBtn);
    panel.appendChild(nameRow);

    // ---- 参数（v0.4.3：脚本 PARAMS meta 兜底合并，旧空参实例也有得改；list 参=逗号文本） ----
    // V1 修：/api/scripts 是 agent 端口专属（group=exec）→ web 端口恒 404、兜底一直静默失效；
    //   改走 web 可读的只读元数据路由 /api/scripts/meta，且失败要出声（不再吞）。
    let metaParams = {};
    try {
        const sr = await fetch('/api/scripts/meta');
        if (!sr.ok) {
            log('info', t('set.meta_fail', {d: sr.status}));
        } else {
            const sd = await sr.json();
            const list = sd.scripts || sd || [];
            const me = list.find(x => x.id === ind.script);
            metaParams = (me && me.params) || {};
        }
    } catch (e) { log('info', t('set.meta_fail', {d: (e && e.message) || e})); }
    const params = { ...metaParams, ...(ind.params || {}) };
    const paramInputs = {};
    if (Object.keys(params).length) {
        panel.appendChild(row(`<div class="set-sec">${t('set.sec_params')}</div>`));
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
                inp.title = t('set.list_ph');
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
    // V1 初值来源 = effectiveStyle（中间层视觉规格 = 图上实际生效色，实例 override 已在其中优先）。
    //   规格色 = Vela 原生默认色（搬运保真）；用户在此改 → 写 lines_style/style → 下次即为 override。
    // P3：native 双源退役 ⇒ 全部指标走 emit，样式（色/线宽/线型/填充/逐点色）一律真实生效
    const caps = { color: true, lineStyle: true, width: true };
    const styleInputs = [];  // {line, color, inks, width, lstyle, auto, isHist}
    const fillInputs = [];   // {key, color, derivedHex, transparency}
    panel.appendChild(row(`<div class="set-sec">${t('set.sec_style')}</div>`));
    const hintOf = (txt) => { const s = document.createElement('span'); s.className = 'set-hint'; s.textContent = txt; return s; };
    const mkStyle = (cur, keyLabel, specLv) => {
        const r = row('');
        if (keyLabel) { const s = document.createElement('span'); s.className = 'set-key'; s.textContent = keyLabel; r.appendChild(s); }
        const color = document.createElement('input');
        color.type = 'color';
        color.value = toHex(cur.color);
        const inks = {};
        // 逐点色语义槽（sar 涨/跌、rsi 低/中/高）：只在 emit 路径可控，且与「单色」互斥
        const useInks = cur.hasInks && !cur.isHist;
        let auto = null, width = null, lstyle = null;
        if (cur.isHist) {
            // 柱状图：仅「自动红绿」（= 原生动能四态色）+ 关闭后的单色（柱宽随 bar 间距，无粗细/线型）
            auto = document.createElement('input');
            auto.type = 'checkbox';
            auto.checked = cur.autoColor;
            auto.title = t('set.auto_rg');
            const sync = () => { color.disabled = auto.checked; };
            auto.onchange = sync; sync();
            r.appendChild(auto); r.appendChild(hintOf(t('set.auto_rg')));
            r.appendChild(hintOf(t('set.hist_color')));
            r.appendChild(color);
        } else if (useInks) {
            Object.keys((specLv && specLv.inks) || {}).forEach(k => {
                const inp = document.createElement('input');
                inp.type = 'color';
                inp.value = toHex(cur.inks[k]);
                inks[k] = inp;
                r.appendChild(hintOf(inkLabel(k)));
                r.appendChild(inp);
            });
        } else {
            r.appendChild(hintOf(t('set.color')));
            r.appendChild(color);
        }
        if (!cur.isHist) {
            if (caps.width) {
                width = document.createElement('input');
                width.type = 'number'; width.min = '1'; width.max = '6'; width.value = cur.lineWidth || 1; width.style.width = '46px';
                r.appendChild(hintOf(t('set.width'))); r.appendChild(width);
            }
            if (caps.lineStyle) {
                lstyle = document.createElement('select');
                LINE_STYLES.forEach(([v, tt]) => { const o = document.createElement('option'); o.value = v; o.textContent = tt; lstyle.appendChild(o); });
                lstyle.value = String(cur.lineStyle ?? 0);
                r.appendChild(hintOf(t('set.style'))); r.appendChild(lstyle);
            }
        }
        panel.appendChild(r);
        return { color, inks, width, lstyle, auto, isHist: cur.isHist };
    };
    if (isMulti) {
        ind.lines.forEach((ln, idx) => {
            const ov = (ind.lines_style || {})[ln.name];
            const cur = effectiveStyle(ind.script || '', ln.name, ln.style, ov, idx, ln.type);
            const specLv = (visualSpec(ind.script || '') || {}).lines || {};
            styleInputs.push({ line: ln.name, ...mkStyle(cur, ln.name, specLv[ln.name]) });
        });
    } else {
        const cur = effectiveStyle(ind.script || '', null, ind.style, ind.style, 0, ind.type);
        styleInputs.push({ line: null, ...mkStyle(cur, null, null) });
    }
    // 填充带（bb 上下轨）：原生默认 = 轨色 8% 透明；改轨色带色跟着走，除非用户在此显式指定
    (specFills(ind.script || '') || []).forEach(f => {
        const key = f.key || 'fillColor';
        const ov = (ind.lines_style || {})[key];
        const anchorName = f.follow || f.from;
        const lines = ind.lines || [];
        const aIdx = Math.max(0, lines.findIndex(l => l.name === anchorName));
        const anchorEff = effectiveStyle(ind.script || '', anchorName,
            (lines[aIdx] || {}).style, (ind.lines_style || {})[anchorName], aIdx);
        const transparency = (ov && ov.transparency != null) ? ov.transparency
            : (f.transparency != null ? f.transparency : 92);
        const derived = effectiveFill(ind.script || '', f, anchorEff.color, ov);
        const r = row('');
        const s = document.createElement('span'); s.className = 'set-key'; s.textContent = t('set.fill'); r.appendChild(s);
        const color = document.createElement('input');
        color.type = 'color';
        color.value = toHex(derived);
        r.appendChild(hintOf(t('set.color'))); r.appendChild(color);
        panel.appendChild(r);
        // anchorColor：同一次保存里轨色可能也被改 → 「是否仍等于派生色」要按保存时的轨色判定
        const anchorInput = (styleInputs.find(si => si.line === anchorName) || {}).color || null;
        fillInputs.push({ key, color, anchorColor: anchorInput, derivedHex: toHex(derived), transparency });
    });

    // ---- 按钮 ----
    const foot = row('');
    foot.className = 'set-foot';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'set-btn primary';
    saveBtn.textContent = t('set.save');
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'set-btn';
    cancelBtn.textContent = t('set.cancel');
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

            // 2) 样式（V1）
            //    · 柱状勾选「自动红绿」⇒ 只发 autoColor，让原生动能四态色生效（发 color 会顶掉策略）
            //    · 逐点色语义槽（sar 涨/跌）⇒ 发 inks，不发 color（同理）
            //    · 填充带只在用户真改了色相时落 override，否则继续「跟随轨色 + 原生透明度」
            const p2 = {};
            const stylePayload = (si, base) => {
                const out = { ...base };
                if (si.isHist) {
                    const on = !!(si.auto && si.auto.checked);
                    out.autoColor = on;
                    if (!on) out.color = si.color.value;
                    return out;
                }
                const inkKeys = Object.keys(si.inks || {});
                if (inkKeys.length) {
                    const ik = {};
                    inkKeys.forEach(k => { ik[k] = si.inks[k].value; });
                    out.inks = ik;
                } else {
                    out.color = si.color.value;
                }
                if (caps.width && si.width) out.lineWidth = parseInt(si.width.value) || 1;
                if (caps.lineStyle && si.lstyle) out.lineStyle = parseInt(si.lstyle.value) || 0;
                return out;
            };
            if (isMulti) {
                const ls = {};
                styleInputs.forEach(si => { ls[si.line] = stylePayload(si, {}); });
                fillInputs.forEach(fi => {
                    const picked = toHex(fi.color.value);
                    // 跟随判定按「保存时的轨色」算派生色：同一次保存里改了轨色也不会误落 override
                    const followHex = toHex(fi.anchorColor ? fi.anchorColor.value : fi.derivedHex);
                    if (picked.toLowerCase() !== followHex.toLowerCase()) {
                        ls[fi.key] = { color: transp(picked, fi.transparency), transparency: fi.transparency };
                    }
                });
                p2.lines_style = ls;
            } else {
                p2.style = stylePayload(styleInputs[0], (ind.style || {}));
            }
            await post(name, p2);

            log('info', t('set.updated', {name}));
            modal.remove();
        } catch (e) {
            log('error', t('set.update_fail', {e}));
        }
    };

    document.body.appendChild(modal);
}

// 颜色输入框只吃 6 位 hex：8 位 hex（原生 transp 填充色）取色相、rgba() 转 hex
const HEX_FALLBACK = '#5b9cf6';   // V1：兜底色改原生 INFO
function toHex(c) {
    if (!c) return HEX_FALLBACK;
    const s = String(c).trim();
    if (/^#[0-9a-f]{6}$/i.test(s)) return s;
    if (/^#[0-9a-f]{8}$/i.test(s)) return s.slice(0, 7);
    if (/^#[0-9a-f]{3}$/i.test(s)) return '#' + [...s.slice(1)].map(x => x + x).join('');
    const m = /^rgba?\(([^)]+)\)$/i.exec(s);
    if (m) {
        const p = m[1].split(',').map(x => parseFloat(x));
        if (p.length >= 3 && p.slice(0, 3).every(Number.isFinite)) {
            return '#' + p.slice(0, 3)
                .map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
        }
    }
    return HEX_FALLBACK;
}
