// ============================================================
// 运行回测（v0.6.1 M3）：引擎 / 策略 / 方向 / 参数 / 成本 / 保护
// 只负责表单与 /api/backtest 调用；结果登记与展示走结果实例（WS result_created）
// ============================================================
import { state } from './state.js';
import { t } from './i18n.js';
import { toast } from './search.js';
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

export async function openBacktestDialog() {
    if (document.getElementById('bt-overlay')) return;
    let engines = [];
    let strategies = [];
    try {
        [engines, strategies] = await Promise.all([loadEngines(), loadStrategies()]);
    } catch (e) {
        toast(`${t('bt.load_fail')}: ${e.message}`);
        return;
    }
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

    const errBox = el('div', 'bt-err');
    const foot = el('div', 'bt-foot');
    const cancel = el('button', 'btn-ghost', t('common.cancel'));
    const run = el('button', 'btn-primary', t('bt.run'));
    foot.append(cancel, run);
    card.appendChild(errBox);
    card.appendChild(foot);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    const close = () => {
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
            })
            .catch(e => { errBox.textContent = `meta: ${e.message}`; });
    };
    stratSel.addEventListener('change', paintParams);
    if (strategies.length) paintParams();

    run.onclick = async () => {
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
