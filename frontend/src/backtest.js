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

    // v0.6.4 模式页签：单次 / 参数矩阵（引擎/策略/方向/窗口/成本共用）
    let mode = 'single';
    const tabs = el('div', 'bt-tabs');
    const tabSingle = el('button', 'bt-tab on', t('bt.tab.single'));
    const tabMatrix = el('button', 'bt-tab', t('bt.tab.matrix'));
    tabSingle.type = tabMatrix.type = 'button';
    tabs.append(tabSingle, tabMatrix);
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
            const acts = el('div', 'bt-preset-acts');
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

    const runLabel = () => (mode === 'matrix' ? t('bt.run_matrix') : t('bt.run'));
    const setMode = (m) => {
        mode = m;
        tabSingle.classList.toggle('on', m === 'single');
        tabMatrix.classList.toggle('on', m === 'matrix');
        paramsBox.style.display = m === 'single' ? '' : 'none';
        matrixBox.style.display = m === 'matrix' ? '' : 'none';
        run.textContent = runLabel();
    };
    tabSingle.onclick = () => setMode('single');
    tabMatrix.onclick = () => setMode('matrix');

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

    run.onclick = async () => {
        if (mode === 'matrix') { await runMatrixNow(); return; }
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
