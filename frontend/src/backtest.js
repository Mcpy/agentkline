// ============================================================
// 运行回测（v0.6.1 M3）：引擎 / 策略 / 方向 / 参数 / 成本 / 保护
// 只负责表单与 /api/backtest 调用；结果登记与展示走结果实例（WS result_created）
// ============================================================
import { state } from './state.js';
import { t } from './i18n.js';
import { toast } from './search.js';
import { openDialog } from './dialog.js';
import { copyText } from './clipboard.js';

import { tfMs } from './vela_adapter.js';

let _engines = null;

async function fetchJSON(url, opts) {
    const r = await fetch(url, { cache: 'no-store', ...(opts || {}) });
    const j = await r.json().catch(() => null);
    if (!r.ok || (j && j.error)) {
        const msg = (j && (j.error || j.detail)) || `HTTP ${r.status}`;
        throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return j || {};
}

async function loadEngines() {
    if (_engines) return _engines;
    const j = await fetchJSON('/api/engines');
    _engines = j.engines || [];
    return _engines;
}

async function loadStrategies() {
    const j = await fetchJSON('/api/strategies');
    return j.strategies || [];
}

function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
}

function row(labelText, control, hint) {
    const r = el('div', 'bt-row');
    r.appendChild(el('label', '', labelText));
    const box = el('div', 'bt-ctl');
    box.appendChild(control);
    if (hint) box.appendChild(el('div', 'bt-hint', hint));
    r.appendChild(box);
    return r;
}

function dateInput() {
    const i = document.createElement('input');
    i.type = 'date';
    return i;
}

function numInput(value, attrs = {}) {
    const i = document.createElement('input');
    i.type = 'number';
    if (value != null) i.value = String(value);
    Object.entries(attrs).forEach(([k, v]) => { if (v != null) i.setAttribute(k, String(v)); });
    return i;
}

function paramControl(name, def, meta) {
    const type = (meta && meta.type) || (typeof def);
    if (type === 'bool') {
        const i = document.createElement('input');
        i.type = 'checkbox';
        i.checked = !!def;
        i.dataset.type = 'bool';
        return i;
    }
    const i = numInput(def, {
        step: (meta && meta.step) || (type === 'int' ? 1 : 'any'),
        min: meta && meta.min, max: meta && meta.max,
    });
    if (type === 'str') {
        i.type = 'text';
        i.value = def == null ? '' : String(def);
        i.dataset.type = 'str';
        return i;
    }
    i.dataset.type = type === 'int' ? 'int' : 'float';
    return i;
}

function readParams(container) {
    const out = {};
    container.querySelectorAll('[data-pname]').forEach(n => {
        const name = n.dataset.pname;
        if (n.dataset.type === 'bool') out[name] = !!n.checked;
        else if (n.dataset.type === 'str') out[name] = n.value;
        else if (n.dataset.type === 'int') out[name] = parseInt(n.value, 10);
        else out[name] = parseFloat(n.value);
        if (typeof out[name] === 'number' && !Number.isFinite(out[name])) delete out[name];
    });
    return out;
}

export async function openBacktestDialog(opts = {}) {
    if (document.getElementById('bt-overlay')) return;
    let engines = [];
    let strategies = [];
    let presets = [];
    try {
        [engines, strategies] = await Promise.all([loadEngines(), loadStrategies()]);
    } catch (e) {
        toast(`${t('bt.load_fail')}: ${e.message}`);
        return;
    }
    if (state.currentBoard) {
        try {
            presets = (await fetchJSON('/api/presets')).presets || [];
        } catch (e) { presets = []; }
    }
    let pendingParams = opts.params || null;   // 从结果/方案带进来的参数
    if (!engines.length) { toast(t('bt.no_engine')); return; }

    const overlay = el('div', 'overlay dialog-overlay');
    overlay.id = 'bt-overlay';
    const card = el('div', 'overlay-card bt-card');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.appendChild(el('h3', '', t('bt.title')));
    card.appendChild(el('div', 'dialog-msg', t('bt.subtitle')));
    const bodyBox = el('div', 'bt-body');
    card.appendChild(bodyBox);

    // v0.6.4 模式页签：单次 / 参数矩阵；v0.6.5 增加参数寻优（引擎/策略/方向/窗口/成本共用）
    let mode = 'single';
    const tabs = el('div', 'bt-tabs');
    const tabSingle = el('button', 'bt-tab on', t('bt.tab.single'));
    const tabMatrix = el('button', 'bt-tab', t('bt.tab.matrix'));
    const tabOptimize = el('button', 'bt-tab', t('bt.tab.optimize'));
    tabSingle.type = tabMatrix.type = tabOptimize.type = 'button';
    tabs.append(tabSingle, tabMatrix, tabOptimize);
    bodyBox.appendChild(tabs);

    // 引擎
    const engineSel = document.createElement('select');
    engines.forEach(e => {
        const o = document.createElement('option');
        o.value = e.id;
        o.textContent = `${e.id} ${e.version || ''}`.trim();
        engineSel.appendChild(o);
    });
    bodyBox.appendChild(row(t('bt.engine'), engineSel));

    // 策略
    const stratSel = document.createElement('select');
    strategies.forEach(s => {
        const o = document.createElement('option');
        o.value = s.id;
        o.textContent = `${s.display || s.id}`;
        o.title = s.desc || s.id;
        stratSel.appendChild(o);
    });
    const stratRow = row(t('bt.strategy'), stratSel,
        strategies.length ? '' : t('bt.no_strategy'));
    bodyBox.appendChild(stratRow);
    if (!strategies.length) {
        stratSel.disabled = true;
    }
    if (opts.script && strategies.some(x => x.id === opts.script)) stratSel.value = opts.script;

    // 参数方案（v0.6.4 收尾）：选方案即填参数；可把当前参数存为该标的的方案
    const presetSel = document.createElement('select');
    presetSel.id = 'bt-preset';
    const presetManage = el('button', 'btn-ghost', t('bt.preset_manage'));
    presetManage.type = 'button';
    const presetImport = el('button', 'btn-ghost', t('bt.import_params'));
    presetImport.type = 'button';
    const presetWrap = el('div', 'bt-preset');
    presetWrap.append(presetSel, presetImport, presetManage);
    bodyBox.appendChild(row(t('bt.preset'), presetWrap));
    const pasteHint = el('div', 'bt-hint');
    pasteHint.style.display = 'none';
    bodyBox.appendChild(pasteHint);
    const boardScope = () => {
        const b = (state.boards || []).find(x => x.id === state.currentBoard);
        const lock = (b && b.source_lock) || {};
        return { source: lock.script || '', symbol: (lock.identity || {}).symbol || '' };
    };
    // 当前标的 + 当前策略可用的方案（下拉用；管理面板可切全局）
    const scopedPresets = () => {
        const sc = boardScope();
        return presets.filter(p =>
            (!sc.source || p.source === sc.source)
            && (!sc.symbol || p.symbol === sc.symbol)
            && (!stratSel.value || p.script === stratSel.value));
    };
    const paintPresets = (selectId = '') => {
        presetSel.textContent = '';
        const none = document.createElement('option');
        none.value = '';
        none.textContent = t('bt.preset_none');
        presetSel.appendChild(none);
        scopedPresets().forEach(p => {
            const o = document.createElement('option');
            o.value = p.id;
            const tf = p.timeframe && p.timeframe !== state.currentTimeframe ? ` · ${p.timeframe}` : '';
            o.textContent = `${p.is_default ? '★ ' : ''}${p.name}${tf}`;
            o.title = Object.entries(p.params || {}).map(([k, v]) => `${k}=${v}`).join(' ');
            presetSel.appendChild(o);
        });
        if (selectId) presetSel.value = selectId;
        else {
            const def = scopedPresets().find(p => p.is_default);
            if (def && !pendingParams) { presetSel.value = def.id; pendingParams = def.params || null; }
        }
    };
    const applyParams = (params) => {
        if (!params) return;
        paramsBox.querySelectorAll('[data-pname]').forEach(n => {
            const k = n.dataset.pname;
            if (!(k in params)) return;
            const v = params[k];
            if (n.dataset.type === 'bool') n.checked = !!v;
            else n.value = String(v);
        });
    };
    presetSel.onchange = () => {
        const hit = presets.find(p => p.id === presetSel.value);
        if (!hit) return;
        pendingParams = hit.params || {};
        applyParams(pendingParams);
        if (mode === 'matrix') paintCount();
    };

    const importParams = async () => {
        const text = await openDialog({
            title: t('bt.paste_title'),
            message: t('bt.paste_hint'),
            textarea: true,
            value: '',
            confirmText: t('bt.paste_ok'),
        });
        if (!text) return;
        let obj = null;
        try { obj = JSON.parse(String(text).trim()); } catch (e) { obj = null; }
        if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
            errBox.textContent = t('bt.paste_bad');
            return;
        }
        const params = obj.params && typeof obj.params === 'object' ? obj.params : obj;
        if (!params || Array.isArray(params)) {
            errBox.textContent = t('bt.paste_bad');
            return;
        }
        let script = typeof obj.script === 'string' ? obj.script : '';
        if (script && script !== stratSel.value && strategies.some(x => x.id === script)) {
            const ok = await openDialog({
                title: t('bt.paste_switch'), message: script,
                confirmText: t('common.ok'),
            });
            if (!ok) return;
            stratSel.value = script;
            paintPresets();
            paintParams();
        } else if (script && !strategies.some(x => x.id === script)) {
            errBox.textContent = t('bt.paste_no_script', { script });
            return;
        }
        pendingParams = params;
        applyParams(params);
        if (meta && meta.params) {
            const unknown = Object.keys(params).filter(k => !(k in meta.params));
            if (unknown.length) {
                errBox.textContent = t('bt.paste_unknown', { keys: unknown.join(', ') });
            }
        }
        const from = obj.from || {};
        pasteHint.textContent = from.symbol
            ? t('bt.paste_from', { symbol: from.symbol, tf: from.timeframe || '' })
            : '';
        pasteHint.style.display = pasteHint.textContent ? '' : 'none';
    };
    presetImport.onclick = importParams;
    paintPresets();

    const reloadPresets = async (selectId = '') => {
        try {
            presets = (await fetchJSON('/api/presets')).presets || [];
        } catch (e) { presets = []; }
        paintPresets(selectId || presetSel.value);
    };

    // 方案管理：默认看本标的，可切全局并按 标的·周期 分组；设默认 / 复制 / 删除
    let _presetScope = 'board';
    const openPresetManager = () => {
        if (document.getElementById('bt-preset-overlay')) return;
        const ov = el('div', 'overlay dialog-overlay');
        ov.id = 'bt-preset-overlay';
        const card = el('div', 'overlay-card dialog-card bt-preset-manager');
        card.appendChild(el('h3', '', t('bt.preset_manage')));
        card.appendChild(el('div', 'dialog-msg', t('bt.preset_manage_hint')));
        const list = el('div', 'bt-preset-list');
        card.appendChild(list);
        let onKey = null;
        const closeOv = () => {
            if (onKey) document.removeEventListener('keydown', onKey, true);
            ov.remove();
        };
        const foot = el('div', 'dialog-foot');
        const closeBtn = el('button', 'btn-primary', t('common.ok'));
        closeBtn.type = 'button';
        closeBtn.onclick = closeOv;
        foot.appendChild(closeBtn);
        card.appendChild(foot);

        let scope = _presetScope;
        let query = '';
        const toolbar = el('div', 'bt-preset-toolbar');
        const boardBtn = el('button', 'bt-tab', t('bt.preset_scope_board'));
        const allBtn = el('button', 'bt-tab', t('bt.preset_scope_all'));
        boardBtn.type = allBtn.type = 'button';
        const search = document.createElement('input');
        search.className = 'bt-preset-search';
        search.placeholder = t('bt.preset_search');
        toolbar.append(boardBtn, allBtn, search);
        card.insertBefore(toolbar, list);
        const syncTabs = () => {
            boardBtn.classList.toggle('on', scope === 'board');
            allBtn.classList.toggle('on', scope === 'all');
        };

        const usePreset = async (p) => {
            if (!strategies.some(x => x.id === p.script)) {
                toast(t('bt.preset_use_missing', { script: p.script }));
                return;
            }
            if (p.script_changed) {
                closeOv();
                const ok = await openDialog({
                    title: t('bt.preset_changed_title'),
                    message: t('bt.preset_changed_msg', { script: p.script }),
                    confirmText: t('common.ok'),
                });
                if (!ok) { openPresetManager(); return; }
            }
            const sc = boardScope();
            const other = (p.symbol && sc.symbol && p.symbol !== sc.symbol)
                || (p.source && sc.source && p.source !== sc.source);
            if (other) {
                closeOv();
                const ok = await openDialog({
                    title: t('bt.preset_use'),
                    message: t('bt.preset_use_other', {
                        source: p.source || '—', symbol: p.symbol,
                        tf: p.timeframe || '—',
                    }),
                    confirmText: t('common.ok'),
                });
                if (!ok) { openPresetManager(); return; }
            } else {
                closeOv();
            }
            if (stratSel.value !== p.script) {
                stratSel.value = p.script;
                paintPresets();
                paintParams();
            }
            pendingParams = p.params || {};
            applyParams(pendingParams);
            presetSel.value = p.id;
            pasteHint.textContent = t('bt.paste_from',
                { symbol: p.symbol, tf: p.timeframe || '' });
            pasteHint.style.display = '';
            toast(t('bt.preset_used', { name: p.name }));
        };

        const presetRow = (p) => {
            const row = el('div', 'bt-preset-item');
            const info = el('div', 'bt-preset-info');
            info.appendChild(el('div', 'bt-preset-name',
                `${p.is_default ? '★ ' : ''}${p.name}`));
            info.appendChild(el('div', 'bt-hint mono',
                Object.entries(p.params || {}).map(([k, v]) => `${k}=${v}`).join(' ')));
            if (scope === 'all') {
                info.appendChild(el('div', 'bt-preset-scope-meta',
                    `${p.script}${p.timeframe ? ' · ' + p.timeframe : ''}`));
            }
            if (p.script_changed) {
                info.appendChild(el('div', 'bt-preset-warn',
                    t('bt.preset_changed_badge')));
            }
            const acts = el('div', 'bt-preset-acts');
            const use = el('button', 'btn-primary', t('bt.preset_use'));
            use.type = 'button';
            use.onclick = () => usePreset(p);
            acts.appendChild(use);
            const cp = el('button', 'btn-ghost', t('bt.preset_copy'));
            cp.type = 'button';
            cp.onclick = async () => {
                const payload = { ak: 'ak.params', v: 1, script: p.script,
                                  params: p.params,
                                  from: { symbol: p.symbol, timeframe: p.timeframe } };
                const ok = await copyText(JSON.stringify(payload));
                if (ok) toast(t('bt.preset_copy_ok'));
                else errBox.textContent = t('result.copy_fail');
            };
            acts.appendChild(cp);
            if (!p.is_default) {
                const bd = el('button', 'btn-ghost', t('bt.preset_set_default'));
                bd.type = 'button';
                bd.onclick = async () => {
                    try {
                        await fetchJSON(`/api/presets/${p.id}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ is_default: true }),
                        });
                        await reloadPresets(scope === 'board' ? p.id : '');
                        paint();
                    } catch (e) { errBox.textContent = e.message; }
                };
                acts.appendChild(bd);
            }
            const del = el('button', 'btn-ghost danger', t('bt.preset_delete'));
            del.type = 'button';
            del.onclick = async () => {
                // 先收起管理面板再弹确认框：两个 overlay 叠着会互相挡点击
                closeOv();
                const ok = await openDialog({
                    title: t('bt.preset_delete'),
                    message: p.name,
                    confirmText: t('result.delete'),
                    danger: true,
                });
                if (!ok) { openPresetManager(); return; }
                try {
                    await fetchJSON(`/api/presets/${p.id}`, { method: 'DELETE' });
                    await reloadPresets('');
                } catch (e) { errBox.textContent = e.message; }
                openPresetManager();
            };
            acts.appendChild(del);
            row.append(info, acts);
            return row;
        };

        const paint = () => {
            list.textContent = '';
            const q = query.trim().toLowerCase();
            const base = scope === 'board' ? scopedPresets() : presets;
            const rows = base.filter(p => !q
                || `${p.symbol} ${p.name} ${p.script} ${p.timeframe || ''}`.toLowerCase().includes(q));
            if (!rows.length) {
                list.appendChild(el('div', 'bt-hint',
                    scope === 'board' ? t('bt.preset_empty') : t('bt.preset_empty_all')));
                return;
            }
            if (scope === 'board') {
                rows.forEach(p => list.appendChild(presetRow(p)));
                return;
            }
            const groups = new Map();
            rows.forEach(p => {
                const key = `${p.symbol} · ${p.timeframe || '—'}`;
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(p);
            });
            [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0])).forEach(([key, items]) => {
                list.appendChild(el('div', 'bt-preset-group', key));
                list.appendChild(el('div', 'bt-preset-group-sub',
                    `${items[0].source} · ${items[0].script}`));
                items.forEach(p => list.appendChild(presetRow(p)));
            });
        };

        boardBtn.onclick = () => { scope = 'board'; _presetScope = scope; syncTabs(); paint(); };
        allBtn.onclick = () => { scope = 'all'; _presetScope = scope; syncTabs(); paint(); };
        search.addEventListener('input', () => { query = search.value; paint(); });
        syncTabs();
        paint();
        onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeOv(); } };
        document.addEventListener('keydown', onKey, true);
        ov.addEventListener('mousedown', (e) => { if (e.target === ov) closeOv(); });
        document.body.appendChild(ov);
        ov.appendChild(card);
    };
    presetManage.onclick = openPresetManager;

    // 方向
    const dirSel = document.createElement('select');
    [['long_only', t('bt.dir.long_only')],
     ['short_only', t('bt.dir.short_only')],
     ['both', t('bt.dir.both')]].forEach(([v, label]) => {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = label;
        dirSel.appendChild(o);
    });
    dirSel.value = 'long_only';
    bodyBox.appendChild(row(t('bt.direction'), dirSel));

    // 时间范围：一行三格（开始 / 结束 / 根数），联动；默认 = 前端已加载的 K 线
    const MAX_RANGE_BARS = 20000;
    const dayMs = 86400000;
    const loaded = (state.ohlcv || []).slice();
    // 用已加载样本的平均 bar 间距而不是固定 1d：股票/有缺口的市场按根数回溯才不虚
    const spacing = loaded.length > 1
        ? (loaded[loaded.length - 1].timestamp - loaded[0].timestamp) / (loaded.length - 1)
        : (tfMs(state.currentTimeframe) || dayMs);
    const latestTs = loaded.length ? loaded[loaded.length - 1].timestamp : Date.now();
    const earliestAllowed = latestTs - (MAX_RANGE_BARS - 1) * spacing;
    const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
    const fmtDate = (ms) => {
        const d = new Date(ms);
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    };
    const parseDate = (v) => {
        const [y, m, d] = String(v || '').split('-').map(Number);
        return (y && m && d) ? new Date(y, m - 1, d).getTime() : null;
    };
    const countInRange = (s, e) => {
        if (loaded.length && s >= loaded[0].timestamp && e <= latestTs) {
            return loaded.filter(b => b.timestamp >= s && b.timestamp < e + dayMs).length;
        }
        return Math.round((e - s) / spacing) + 1;
    };

    let startMs = Math.max(loaded.length ? loaded[0].timestamp : earliestAllowed, earliestAllowed);
    let endMs = loaded.length ? latestTs : Date.now();
    if (endMs < startMs) endMs = startMs;

    const startD = dateInput();
    const endD = dateInput();
    const barsIn = numInput(null, { min: 1, max: MAX_RANGE_BARS, step: 1 });
    startD.id = 'bt-start';
    endD.id = 'bt-end';
    barsIn.id = 'bt-bars';
    startD.title = t('bt.start');
    endD.title = t('bt.end');
    barsIn.title = t('bt.lookback');
    const rangeBox = el('div', 'bt-range');
    rangeBox.append(startD, endD, barsIn);
    bodyBox.appendChild(row(t('bt.range'), rangeBox, t('bt.range_hint')));

    let syncing = false;
    const syncRange = () => {
        if (syncing) return;
        syncing = true;
        startD.value = fmtDate(startMs);
        endD.value = fmtDate(endMs);
        barsIn.value = String(Math.max(1, countInRange(startMs, endMs)));
        syncing = false;
    };
    syncRange();

    startD.addEventListener('change', () => {
        const v = parseDate(startD.value);
        if (v == null) { syncRange(); return; }
        startMs = clamp(v, earliestAllowed, endMs);
        syncRange();
    });
    endD.addEventListener('change', () => {
        const v = parseDate(endD.value);
        if (v == null) { syncRange(); return; }
        endMs = clamp(v, startMs, latestTs);
        syncRange();
    });
    barsIn.addEventListener('change', () => {
        let n = parseInt(barsIn.value, 10);
        if (!Number.isFinite(n)) { syncRange(); return; }
        n = clamp(n, 1, MAX_RANGE_BARS);
        startMs = Math.max(endMs - (n - 1) * spacing, earliestAllowed);
        syncRange();
    });

    // 成本
    const cash = numInput(10000, { min: 1, step: 'any' });
    const fee = numInput(5, { min: 0, step: '0.1' });
    const slip = numInput(5, { min: 0, step: '0.1' });
    bodyBox.appendChild(row(t('bt.cash'), cash, t('bt.cash_hint')));
    bodyBox.appendChild(row(t('bt.fee'), fee, t('bt.fee_hint')));
    bodyBox.appendChild(row(t('bt.slip'), slip, t('bt.slip_hint')));

    // 保护（可选，按百分比输入）
    const sl = numInput(null, { min: 0, max: 99, step: '0.1', placeholder: t('bt.off') });
    const tp = numInput(null, { min: 0, max: 999, step: '0.1', placeholder: t('bt.off') });
    bodyBox.appendChild(row(t('bt.stop'), sl, t('bt.stop_hint')));
    bodyBox.appendChild(row(t('bt.take'), tp));

    // 参数（按策略声明动态渲染）
    const paramsBox = el('div', 'bt-params');
    bodyBox.appendChild(paramsBox);
    const matrixBox = el('div', 'bt-matrix');
    matrixBox.style.display = 'none';
    bodyBox.appendChild(matrixBox);
    const optimizeBox = el('div', 'bt-optimize');
    optimizeBox.style.display = 'none';
    bodyBox.appendChild(optimizeBox);

    const prog = el('div', 'bt-progress');
    prog.style.display = 'none';
    let progTimer = null;
    const stopProg = () => {
        if (progTimer) { clearInterval(progTimer); progTimer = null; }
    };
    const errBox = el('div', 'bt-err');
    const foot = el('div', 'bt-foot');
    const cancel = el('button', 'btn-ghost', t('common.cancel'));
    const run = el('button', 'btn-primary', t('bt.run'));
    foot.append(cancel, run);
    card.appendChild(prog);
    card.appendChild(errBox);
    card.appendChild(foot);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    const close = () => {
        stopProg();
        document.removeEventListener('keydown', onKey, true);
        overlay.remove();
    };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    document.addEventListener('keydown', onKey, true);
    cancel.onclick = close;
    overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

    let meta = null;
    const paintParams = () => {
        paramsBox.textContent = '';
        meta = null;
        if (!stratSel.value) return;
        fetchJSON(`/api/strategy/meta?script=${encodeURIComponent(stratSel.value)}`)
            .then(j => {
                meta = j;
                if (j.error) { errBox.textContent = j.error; return; }
                const desc = el('div', 'bt-meta');
                const bits = [];
                if (j.name) bits.push(j.name);
                if (j.warmup != null) bits.push(`WARMUP ${j.warmup}`);
                if (j.bars_per_year) bits.push(`${j.bars_per_year}/yr`);
                desc.textContent = bits.join(' · ');
                paramsBox.appendChild(desc);
                if (j.desc) paramsBox.appendChild(el('div', 'bt-hint', j.desc));
                if (j.errors && j.errors.length) {
                    const e = j.errors[0];
                    errBox.textContent = `${e.code}: ${e.message}`;
                }
                paintMatrix(j);
                paintOptimize(j);
                const params = j.params || {};
                const metaMap = j.param_meta || {};
                const keys = Object.keys(params);
                if (keys.length) {
                    paramsBox.appendChild(el('div', 'bt-sec', t('bt.params')));
                    keys.forEach(k => {
                        const ctl = paramControl(k, params[k], metaMap[k]);
                        ctl.dataset.pname = k;
                        const label = (metaMap[k] && metaMap[k].label) || k;
                        paramsBox.appendChild(row(label, ctl,
                            metaMap[k] && metaMap[k].min != null
                                ? `${metaMap[k].min} ~ ${metaMap[k].max ?? '∞'}` : ''));
                    });
                }
                if (pendingParams) applyParams(pendingParams);
            })
            .catch(e => { errBox.textContent = `meta: ${e.message}`; });
    };
    // ---- 参数矩阵输入（v0.6.4）：多值用逗号分隔，组合数实时预览 ----
    const MATRIX_MAX = 60;
    const matrixInputs = () => [...matrixBox.querySelectorAll('input[data-mgrid]')];
    const readGrid = () => {
        const grid = {};
        matrixInputs().forEach(inp => {
            const raw = inp.value.trim();
            if (!raw) return;
            grid[inp.dataset.mgrid] = raw.split(',')
                .map(x => x.trim()).filter(x => x !== '')
                .map(x => (Number.isFinite(Number(x)) ? Number(x) : x));
        });
        return grid;
    };
    const gridCount = (grid) => {
        const keys = Object.keys(grid);
        if (!keys.length) return 0;
        return keys.reduce((n, k) => n * Math.max(1, grid[k].length), 1);
    };
    const paintCount = () => {
        const cnt = document.getElementById('bt-matrix-count');
        if (!cnt) return;
        const n = gridCount(readGrid());
        if (!n) {
            cnt.textContent = t('bt.matrix.empty');
            cnt.classList.remove('err');
            return;
        }
        if (n > MATRIX_MAX) {
            cnt.textContent = t('bt.matrix.limit', { n, max: MATRIX_MAX });
            cnt.classList.add('err');
            return;
        }
        cnt.textContent = t('bt.matrix.count', { n });
        cnt.classList.remove('err');
    };
    const paintMatrix = (meta) => {
        matrixBox.textContent = '';
        if (!meta) return;
        matrixBox.appendChild(el('div', 'bt-sec', t('bt.matrix.title')));
        matrixBox.appendChild(el('div', 'bt-hint', t('bt.matrix.hint')));
        const params = meta.params || {};
        const metaMap = meta.param_meta || {};
        const numeric = Object.keys(params).filter(k => {
            const typ = (metaMap[k] && metaMap[k].type) || typeof params[k];
            return typ === 'int' || typ === 'float';
        });
        if (!numeric.length) {
            matrixBox.appendChild(el('div', 'bt-hint', t('bt.matrix.no_numeric')));
        }
        numeric.forEach(k => {
            const m = metaMap[k] || {};
            const inp = document.createElement('input');
            inp.type = 'text';
            inp.dataset.mgrid = k;
            inp.placeholder = `${params[k]} (${t('bt.matrix.values_hint')})`;
            const bound = m.min != null ? `${m.min} ~ ${m.max ?? '∞'}` : '';
            matrixBox.appendChild(row(`${m.label || k}${bound ? ` (${bound})` : ''}`, inp));
            inp.addEventListener('input', paintCount);
        });
        const cnt = el('div', 'bt-hint bt-matrix-count');
        cnt.id = 'bt-matrix-count';
        matrixBox.appendChild(cnt);
        paintCount();
    };

    // ---- v0.6.5 参数寻优：空间/目标/约束/预算/样本外 ----
    const OPT_METRICS = ['total_return', 'annual_return', 'sharpe', 'sortino',
                         'calmar', 'max_drawdown', 'profit_factor', 'win_rate'];
    const paintOptimize = (meta) => {
        optimizeBox.textContent = '';
        if (!meta) return;
        optimizeBox.appendChild(el('div', 'bt-sec', t('bt.opt.title')));
        optimizeBox.appendChild(el('div', 'bt-hint', t('bt.opt.hint')));
        const params = meta.params || {};
        const metaMap = meta.param_meta || {};
        const numeric = Object.keys(params).filter(k => {
            const typ = (metaMap[k] && metaMap[k].type) || typeof params[k];
            return typ === 'int' || typ === 'float';
        });

        const method = document.createElement('select');
        method.id = 'bt-opt-method';
        [['bayes', t('bt.opt.method.bayes')],
         ['grid', t('bt.opt.method.grid')],
         ['random', t('bt.opt.method.random')]].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            method.appendChild(o);
        });
        optimizeBox.appendChild(row(t('bt.opt.method'), method, t('bt.opt.method_hint')));

        const metric = document.createElement('select');
        metric.id = 'bt-opt-metric';
        OPT_METRICS.forEach(m => {
            const o = document.createElement('option');
            o.value = m;
            o.textContent = t(`bt.opt.metric.${m}`);
            metric.appendChild(o);
        });
        metric.value = 'sharpe';
        const direction = document.createElement('select');
        direction.id = 'bt-opt-direction';
        [['max', t('bt.opt.dir.max')], ['min', t('bt.opt.dir.min')]].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            direction.appendChild(o);
        });
        const objWrap = el('div', 'bt-inline');
        objWrap.append(metric, direction);
        optimizeBox.appendChild(row(t('bt.opt.objective'), objWrap, t('bt.opt.objective_hint')));

        const minTrades = numInput(null, { min: 0, step: 1, placeholder: t('bt.opt.off') });
        minTrades.id = 'bt-opt-mintrades';
        const maxDd = numInput(null, { min: 0, max: 99, step: '1', placeholder: t('bt.opt.off') });
        maxDd.id = 'bt-opt-maxdd';
        const consWrap = el('div', 'bt-inline');
        consWrap.append(minTrades, maxDd);
        optimizeBox.appendChild(row(t('bt.opt.constraints'), consWrap, t('bt.opt.constraints_hint')));

        const maxRuns = numInput(40, { min: 2, max: 200, step: 1 });
        maxRuns.id = 'bt-opt-runs';
        const maxSeconds = numInput(600, { min: 10, max: 3600, step: 10 });
        maxSeconds.id = 'bt-opt-seconds';
        const budgetWrap = el('div', 'bt-inline');
        budgetWrap.append(maxRuns, maxSeconds);
        optimizeBox.appendChild(row(t('bt.opt.budget'), budgetWrap, t('bt.opt.budget_hint')));

        const ratio = document.createElement('select');
        ratio.id = 'bt-opt-ratio';
        [['0', t('bt.opt.holdout_off')], ['0.2', '20%'], ['0.3', '30%'],
         ['0.4', '40%'], ['0.5', '50%']].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            ratio.appendChild(o);
        });
        ratio.value = '0.3';
        const topK = numInput(3, { min: 1, max: 10, step: 1 });
        topK.id = 'bt-opt-topk';
        const holdWrap = el('div', 'bt-inline');
        holdWrap.append(ratio, topK);
        optimizeBox.appendChild(row(t('bt.opt.holdout'), holdWrap, t('bt.opt.holdout_hint')));

        optimizeBox.appendChild(el('div', 'bt-sec', t('bt.opt.space')));
        optimizeBox.appendChild(el('div', 'bt-hint', t('bt.opt.space_hint')));
        if (!numeric.length) {
            optimizeBox.appendChild(el('div', 'bt-hint', t('bt.matrix.no_numeric')));
        }
        numeric.forEach(k => {
            const m = metaMap[k] || {};
            const box = el('div', 'bt-space');
            box.dataset.osk = k;
            const bound = m.min != null ? `${m.min} ~ ${m.max ?? '∞'}` : '';
            box.appendChild(el('div', 'bt-space-head',
                `${m.label || k}${bound ? ` (${bound})` : ''} · ${t('bt.opt.default')}=${params[k]}`));
            const grid = el('div', 'bt-space-grid');
            const mk = (label, key, attrs) => {
                const wrap = el('label', 'bt-space-cell');
                wrap.appendChild(el('span', '', label));
                const inp = numInput(null, { step: (m.step || (m.type === 'int' ? 1 : 'any')), ...attrs });
                inp.dataset[key] = '1';
                wrap.appendChild(inp);
                return wrap;
            };
            grid.append(
                mk(t('bt.opt.min'), 'omin', { min: m.min, max: m.max }),
                mk(t('bt.opt.max'), 'omax', { min: m.min, max: m.max }),
                mk(t('bt.opt.step'), 'ostep', { min: 0 }),
            );
            const vals = document.createElement('input');
            vals.type = 'text';
            vals.dataset.ovalues = '1';
            vals.placeholder = t('bt.opt.values_ph');
            grid.appendChild(vals);
            box.appendChild(grid);
            optimizeBox.appendChild(box);
        });
    };

    const readOptimizeSpace = () => {
        const space = {};
        let partial = '';
        optimizeBox.querySelectorAll('[data-osk]').forEach(box => {
            const key = box.dataset.osk;
            const v = box.querySelector('[data-ovalues]');
            if (v && v.value.trim()) {
                const vals = v.value.split(',').map(x => x.trim()).filter(x => x !== '')
                    .map(x => (Number.isFinite(Number(x)) ? Number(x) : x));
                if (vals.length) space[key] = { values: vals };
                return;
            }
            const lo = box.querySelector('[data-omin]').value.trim();
            const hi = box.querySelector('[data-omax]').value.trim();
            if (!lo && !hi) return;
            if (!lo || !hi) { partial = key; return; }
            const spec = { min: Number(lo), max: Number(hi) };
            const step = box.querySelector('[data-ostep]').value.trim();
            if (step) spec.step = Number(step);
            space[key] = spec;
        });
        if (partial) {
            return { error: t('bt.opt.space_partial', { key: partial }) };
        }
        if (!Object.keys(space).length) {
            return { error: t('bt.opt.space_empty') };
        }
        return { space };
    };

    const fmtMetric = (key, v) => {
        if (v == null || !Number.isFinite(Number(v))) return '—';
        const n = Number(v);
        if (key === 'total_return' || key === 'annual_return'
            || key === 'max_drawdown' || key === 'win_rate') {
            return `${(n * 100).toFixed(2)}%`;
        }
        return n.toFixed(3);
    };
    const fmtParams = (p) => Object.entries(p || {})
        .map(([k, v]) => `${k}=${v}`).join(' ');
    // 结果模块监听 ak:open-result（避免 backtest ↔ results 静态循环）
    const focusResult = (id) => window.dispatchEvent(
        new CustomEvent('ak:open-result', { detail: { id } }));

    const openOptimizeReport = (st) => {
        if (document.getElementById('bt-opt-report-overlay')) return;
        const ov = el('div', 'overlay dialog-overlay');
        ov.id = 'bt-opt-report-overlay';
        const card = el('div', 'overlay-card dialog-card bt-opt-report');
        card.appendChild(el('h3', '', t('bt.opt.report')));
        const metricKey = (st.objective && st.objective.metric) || 'sharpe';
        const best = st.best;
        card.appendChild(el('div', 'dialog-msg',
            `${t('bt.opt.method')}: ${st.method} · ${metricKey} · ${t('bt.opt.elapsed')} `
            + `${((st.elapsed_ms || 0) / 1000).toFixed(1)}s`
            + (st.seed != null ? ` · seed=${st.seed}` : '')));
        if (best) {
            const box = el('div', 'bt-opt-best');
            box.appendChild(el('div', 'bt-opt-best-title', t('bt.opt.best')));
            box.appendChild(el('div', 'bt-opt-best-params mono', fmtParams(best.params)));
            card.appendChild(box);
        } else {
            card.appendChild(el('div', 'bt-opt-empty', t('bt.opt.no_best')));
        }
        const warns = (st.warnings || []).filter(w =>
            ['OOS_DEGRADED', 'OOS_NO_EDGE', 'OOS_INVALID', 'NO_OOS_VALID',
             'NO_HOLDOUT', 'TIME_BUDGET', 'NO_VALID_TRIAL'].includes(w.code));
        if (warns.length) {
            const wbox = el('div', 'bt-opt-warn');
            warns.slice(0, 6).forEach(w => {
                wbox.appendChild(el('div', '', `⚠ ${w.message || w.code}`));
            });
            card.appendChild(wbox);
        }
        if (best) {
            const tbl = el('table', 'bt-opt-metrics');
            const head = document.createElement('tr');
            [t('bt.opt.metric'), 'IS', 'OOS'].forEach(h => {
                const th = document.createElement('th');
                th.textContent = h;
                head.appendChild(th);
            });
            tbl.appendChild(head);
            [['total_return', t('bt.opt.metric.total_return')],
             ['annual_return', t('bt.opt.metric.annual_return')],
             ['sharpe', t('bt.opt.metric.sharpe')],
             ['max_drawdown', t('bt.opt.metric.max_drawdown')],
             ['win_rate', t('bt.opt.metric.win_rate')],
             ['trade_count', t('bt.opt.metric.trade_count')]].forEach(([k, label]) => {
                const tr = document.createElement('tr');
                tr.appendChild(el('td', '', label));
                const isv = (best.is_stats || {})[k];
                const oosv = (best.oos_stats || {})[k];
                tr.appendChild(el('td', '', k === 'trade_count'
                    ? String(isv ?? '—') : fmtMetric(k, isv)));
                tr.appendChild(el('td', '', k === 'trade_count'
                    ? String(oosv ?? '—') : fmtMetric(k, oosv)));
                tbl.appendChild(tr);
            });
            card.appendChild(tbl);
            const acts = el('div', 'bt-opt-acts');
            if (best.result_id) {
                const view = el('button', 'btn-primary', t('bt.opt.view_result'));
                view.type = 'button';
                view.onclick = async () => {
                    ov.remove();
                    try { focusResult(best.result_id); } catch (e) { /* 结果已淘汰 */ }
                };
                acts.appendChild(view);
            }
            const save = el('button', 'btn-ghost', t('bt.opt.save_preset'));
            save.type = 'button';
            save.onclick = async () => {
                const def = `${t('bt.opt.preset_prefix')} ${fmtParams(best.params)}`.slice(0, 80);
                const name = await openDialog({
                    title: t('bt.opt.save_preset'), value: def,
                    confirmText: t('bt.opt.save_preset'),
                });
                if (!name) return;
                try {
                    const payload = {
                        board_id: st.board_id, script: st.script,
                        timeframe: st.timeframe, name, params: best.params,
                    };
                    if (best.result_id) payload.origin_result_id = best.result_id;
                    await fetchJSON('/api/presets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    toast(t('bt.opt.preset_saved', { name }));
                } catch (e) { toast(`${t('bt.opt.preset_fail')}: ${e.message}`); }
            };
            acts.appendChild(save);
            const cp = el('button', 'btn-ghost', t('bt.preset_copy'));
            cp.type = 'button';
            cp.onclick = async () => {
                const payload = { ak: 'ak.params', v: 1, script: st.script,
                                  params: best.params,
                                  from: { timeframe: st.timeframe } };
                const ok = await copyText(JSON.stringify(payload));
                toast(ok ? t('bt.preset_copy_ok') : t('result.copy_fail'));
            };
            acts.appendChild(cp);
            card.appendChild(acts);
        }
        card.appendChild(el('div', 'bt-sec', t('bt.opt.trials')));
        const wrap = el('div', 'bt-opt-trials');
        const tbl = el('table', 'bt-opt-trial-table');
        const thead = document.createElement('tr');
        ['#', t('bt.opt.params'), t('bt.opt.status'), 'IS', 'OOS', ''].forEach(h => {
            const th = document.createElement('th');
            th.textContent = h;
            thead.appendChild(th);
        });
        tbl.appendChild(thead);
        const rows = [...(st.trials || [])].sort((a, b) => {
            const sa = a.oos_score ?? a.score;
            const sb = b.oos_score ?? b.score;
            return (sb == null ? -Infinity : sb) - (sa == null ? -Infinity : sa);
        });
        rows.slice(0, 200).forEach(tr0 => {
            const tr = document.createElement('tr');
            tr.appendChild(el('td', '', String((tr0.index ?? 0) + 1)));
            tr.appendChild(el('td', 'mono', fmtParams(tr0.params)));
            const status = tr0.oos_status || tr0.status;
            const stext = status === 'ok' ? t('bt.opt.st.ok')
                : status === 'rejected' ? t('bt.opt.st.rejected')
                : status === 'invalid' ? t('bt.opt.st.invalid') : t('bt.opt.st.failed');
            const std = el('td', `bt-opt-st ${status || ''}`, stext);
            if (tr0.reason || tr0.oos_reason) std.title = tr0.oos_reason || tr0.reason;
            tr.appendChild(std);
            tr.appendChild(el('td', '', fmtMetric(metricKey, tr0.value)));
            tr.appendChild(el('td', '', fmtMetric(metricKey, tr0.oos_value)));
            const act = el('td', '');
            if (tr0.result_id) {
                const v = el('button', 'btn-ghost', t('bt.opt.view'));
                v.type = 'button';
                v.onclick = async () => {
                    ov.remove();
                    try { focusResult(tr0.result_id); } catch (e) { /* 结果已淘汰 */ }
                };
                act.appendChild(v);
            }
            tr.appendChild(act);
            tbl.appendChild(tr);
        });
        wrap.appendChild(tbl);
        card.appendChild(wrap);
        const foot = el('div', 'dialog-foot');
        const closeBtn = el('button', 'btn-primary', t('common.close'));
        closeBtn.type = 'button';
        closeBtn.onclick = () => ov.remove();
        foot.appendChild(closeBtn);
        card.appendChild(foot);
        const onKey = (e) => {
            if (e.key === 'Escape') { e.stopPropagation(); ov.remove(); }
        };
        document.addEventListener('keydown', onKey, true);
        ov.addEventListener('mousedown', (e) => { if (e.target === ov) ov.remove(); });
        ov.appendChild(card);
        document.body.appendChild(ov);
    };

    const runLabel = () => (mode === 'matrix' ? t('bt.run_matrix')
        : mode === 'optimize' ? t('bt.run_optimize') : t('bt.run'));
    const setMode = (m) => {
        mode = m;
        tabSingle.classList.toggle('on', m === 'single');
        tabMatrix.classList.toggle('on', m === 'matrix');
        tabOptimize.classList.toggle('on', m === 'optimize');
        paramsBox.style.display = m === 'single' ? '' : 'none';
        matrixBox.style.display = m === 'matrix' ? '' : 'none';
        optimizeBox.style.display = m === 'optimize' ? '' : 'none';
        run.textContent = runLabel();
    };
    tabSingle.onclick = () => setMode('single');
    tabMatrix.onclick = () => setMode('matrix');
    tabOptimize.onclick = () => setMode('optimize');

    stratSel.addEventListener('change', () => { paintPresets(); paintParams(); });
    if (strategies.length) paintParams();

    const runMatrixNow = async () => {
        errBox.textContent = '';
        const grid = readGrid();
        const n = gridCount(grid);
        if (!n) { errBox.textContent = t('bt.matrix.empty'); return; }
        if (n > MATRIX_MAX) {
            errBox.textContent = t('bt.matrix.limit', { n, max: MATRIX_MAX });
            return;
        }
        run.disabled = true;
        cancel.disabled = true;
        const old = run.textContent;
        run.textContent = t('bt.matrix.starting');
        try {
            const body = {
                board_id: state.currentBoard,
                timeframe: state.currentTimeframe,
                engine: engineSel.value,
                script: stratSel.value || null,
                direction: dirSel.value,
                initial_cash: parseFloat(cash.value),
                fee_bps: parseFloat(fee.value),
                slippage_bps: parseFloat(slip.value),
                grid,
                start_time: startMs,
                end_time: endMs + dayMs - 1,
                limit: clamp(parseInt(barsIn.value, 10) || MAX_RANGE_BARS, 1, MAX_RANGE_BARS),
            };
            const protection = {};
            if (sl.value !== '') protection.stop_loss_pct = parseFloat(sl.value) / 100;
            if (tp.value !== '') protection.take_profit_pct = parseFloat(tp.value) / 100;
            if (Object.keys(protection).length) body.protection = protection;
            const j = await fetchJSON('/api/backtest/matrix', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const jobId = j.job_id;
            const pText = el('span', 'bt-progress-text',
                t('bt.matrix.running', { done: 0, total: j.total }));
            const pCancel = el('button', 'btn-ghost', t('bt.matrix.cancel'));
            pCancel.type = 'button';
            pCancel.onclick = async () => {
                pCancel.disabled = true;
                try {
                    await fetchJSON(`/api/backtest/matrix/${jobId}/cancel`, { method: 'POST' });
                } catch (e) { /* 由轮询收尾 */ }
            };
            prog.textContent = '';
            prog.append(pText, pCancel);
            prog.style.display = '';
            stopProg();
            progTimer = setInterval(async () => {
                try {
                    const st = await fetchJSON(`/api/backtest/matrix/${jobId}`);
                    const cur = st.current
                        ? Object.entries(st.current).map(([k, v]) => `${k}=${v}`).join(' ')
                        : '';
                    pText.textContent = t('bt.matrix.running',
                        { done: st.done, total: st.total }) + (cur ? ` · ${cur}` : '');
                    if (st.status !== 'running') {
                        stopProg();
                        const okN = (st.results || []).length;
                        const errN = (st.errors || []).length;
                        toast(st.status === 'cancelled'
                            ? t('bt.matrix.cancelled', { done: st.done, total: st.total })
                            : t('bt.matrix.done', { ok: okN, err: errN }));
                        close();
                    }
                } catch (e) {
                    stopProg();
                    errBox.textContent = e.message;
                    run.disabled = false;
                    cancel.disabled = false;
                    run.textContent = old;
                }
            }, 600);
        } catch (e) {
            errBox.textContent = e.message;
            run.disabled = false;
            cancel.disabled = false;
            run.textContent = old;
        }
    };

    const runOptimizeNow = async () => {
        errBox.textContent = '';
        if (!meta) { errBox.textContent = t('bt.opt.no_meta'); return; }
        const sp = readOptimizeSpace();
        if (sp.error) { errBox.textContent = sp.error; return; }
        const metric = document.getElementById('bt-opt-metric').value;
        const direction = document.getElementById('bt-opt-direction').value;
        const minTrades = document.getElementById('bt-opt-mintrades').value.trim();
        const maxDdPct = document.getElementById('bt-opt-maxdd').value.trim();
        const maxRuns = parseInt(document.getElementById('bt-opt-runs').value, 10) || 40;
        const maxSeconds = parseInt(document.getElementById('bt-opt-seconds').value, 10) || 600;
        const ratio = parseFloat(document.getElementById('bt-opt-ratio').value) || 0;
        const topK = parseInt(document.getElementById('bt-opt-topk').value, 10) || 3;
        const constraints = {};
        if (minTrades) constraints.min_trades = parseInt(minTrades, 10);
        if (maxDdPct) constraints.max_drawdown = parseFloat(maxDdPct) / 100;
        const body = {
            board_id: state.currentBoard,
            timeframe: state.currentTimeframe,
            engine: engineSel.value,
            script: stratSel.value || null,
            direction: dirSel.value,
            initial_cash: parseFloat(cash.value),
            fee_bps: parseFloat(fee.value),
            slippage_bps: parseFloat(slip.value),
            space: sp.space,
            method: document.getElementById('bt-opt-method').value,
            objective: { metric, direction },
            constraints,
            budget: { max_runs: Math.max(2, Math.min(200, maxRuns)),
                      max_seconds: Math.max(10, Math.min(3600, maxSeconds)) },
            holdout: { ratio, top_k: Math.max(1, Math.min(10, topK)) },
            start_time: startMs,
            end_time: endMs + dayMs - 1,
            limit: clamp(parseInt(barsIn.value, 10) || MAX_RANGE_BARS, 1, MAX_RANGE_BARS),
        };
        const protection = {};
        if (sl.value !== '') protection.stop_loss_pct = parseFloat(sl.value) / 100;
        if (tp.value !== '') protection.take_profit_pct = parseFloat(tp.value) / 100;
        if (Object.keys(protection).length) body.protection = protection;
        run.disabled = true;
        cancel.disabled = true;
        const old = run.textContent;
        run.textContent = t('bt.opt.starting');
        try {
            const j = await fetchJSON('/api/backtest/optimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const jobId = j.job_id;
            const pText = el('span', 'bt-progress-text', t('bt.opt.running', { done: 0, total: j.total }));
            const pCancel = el('button', 'btn-ghost', t('bt.opt.cancel'));
            pCancel.type = 'button';
            pCancel.onclick = async () => {
                pCancel.disabled = true;
                try {
                    await fetchJSON(`/api/backtest/optimize/${jobId}/cancel`, { method: 'POST' });
                } catch (e) { /* 由轮询收尾 */ }
            };
            prog.textContent = '';
            prog.append(pText, pCancel);
            prog.style.display = '';
            stopProg();
            progTimer = setInterval(async () => {
                try {
                    const st = await fetchJSON(`/api/backtest/optimize/${jobId}`);
                    const phase = st.phase === 'oos' ? t('bt.opt.phase_oos')
                        : st.phase === 'register' ? t('bt.opt.phase_register')
                        : st.phase === 'done' ? t('bt.opt.phase_done') : t('bt.opt.phase_is');
                    const done = st.phase === 'oos' ? (st.oos_done || 0) : st.done;
                    const total = st.phase === 'oos'
                        ? ((st.holdout && st.holdout.top_k) || 0) : st.total;
                    const cur = st.current ? fmtParams(st.current) : '';
                    pText.textContent = `${phase} ${done}/${total}`
                        + (cur ? ` · ${cur}` : '');
                    if (st.status !== 'running') {
                        stopProg();
                        run.disabled = false;
                        cancel.disabled = false;
                        run.textContent = old;
                        if (st.status === 'failed') {
                            const err = (st.errors && st.errors[0] && st.errors[0].error)
                                || t('bt.opt.failed');
                            errBox.textContent = err;
                            return;
                        }
                        close();
                        openOptimizeReport(st);
                    }
                } catch (e) {
                    stopProg();
                    errBox.textContent = e.message;
                    run.disabled = false;
                    cancel.disabled = false;
                    run.textContent = old;
                }
            }, 700);
        } catch (e) {
            errBox.textContent = e.message;
            run.disabled = false;
            cancel.disabled = false;
            run.textContent = old;
        }
    };

    run.onclick = async () => {
        if (mode === 'matrix') { await runMatrixNow(); return; }
        if (mode === 'optimize') { await runOptimizeNow(); return; }
        errBox.textContent = '';
        run.disabled = true;
        cancel.disabled = true;
        const old = run.textContent;
        run.textContent = t('bt.running');
        try {
            const body = {
                board_id: state.currentBoard,
                timeframe: state.currentTimeframe,
                engine: engineSel.value,
                script: stratSel.value || null,
                direction: dirSel.value,
                initial_cash: parseFloat(cash.value),
                fee_bps: parseFloat(fee.value),
                slippage_bps: parseFloat(slip.value),
                params: readParams(paramsBox),
                start_time: startMs,
                end_time: endMs + dayMs - 1,
                limit: clamp(parseInt(barsIn.value, 10) || MAX_RANGE_BARS,
                             1, MAX_RANGE_BARS),
            };
            const protection = {};
            if (sl.value !== '') protection.stop_loss_pct = parseFloat(sl.value) / 100;
            if (tp.value !== '') protection.take_profit_pct = parseFloat(tp.value) / 100;
            if (Object.keys(protection).length) body.protection = protection;
            const j = await fetchJSON('/api/backtest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const r = j.result || {};
            if (j.run && j.run.clipped) {
                toast(t('bt.clipped', {
                    from: new Date(j.run.from).toLocaleDateString(),
                }));
            }
            toast(t('bt.done', {
                name: r.display_name || r.result_id || '',
                n: (r.stats && r.stats.trade_count) || 0,
                b: (j.run && j.run.bars) || 0,
                ms: (j.run && j.run.elapsed_ms) || 0,
            }));
            close();
        } catch (e) {
            errBox.textContent = e.message;
            run.disabled = false;
            cancel.disabled = false;
            run.textContent = old;
        }
    };
}
