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

function groupHead(num, title, sub) {
    const h = el('div', 'bt-group-head');
    h.append(el('span', 'bt-group-num', String(num)),
             el('span', 'bt-group-title', title));
    if (sub) h.appendChild(el('span', 'bt-group-sub', sub));
    return h;
}

function subHead(text) {
    return el('div', 'bt-subhead', text);
}

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

const fmtShortDate = (ts) => {
    if (!ts) return '—';
    try { return new Date(Number(ts)).toLocaleDateString(); } catch (e) { return '—'; }
};
export const openOptimizeHistory = async () => {
    if (document.getElementById('bt-opt-history-overlay')) return;
    const ov = el('div', 'overlay dialog-overlay');
    ov.id = 'bt-opt-history-overlay';
    const card = el('div', 'overlay-card dialog-card bt-opt-history-card');
    card.appendChild(el('h3', '', t('bt.opt.history_title')));
    const toolbar = el('div', 'bt-preset-toolbar bt-opt-history-toolbar');
    const boardBtn = el('button', 'bt-tab', t('bt.opt.history_scope_board'));
    const allBtn = el('button', 'bt-tab', t('bt.opt.history_scope_all'));
    boardBtn.type = allBtn.type = 'button';
    const search = document.createElement('input');
    search.className = 'bt-preset-search';
    search.placeholder = t('bt.opt.history_search');
    toolbar.append(boardBtn, allBtn, search);
    card.appendChild(toolbar);
    const list = el('div', 'bt-opt-history-list');
    card.appendChild(list);
    const foot = el('div', 'dialog-foot');
    const closeBtn = el('button', 'btn-primary', t('common.close'));
    closeBtn.type = 'button';
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const close = () => {
        document.removeEventListener('keydown', onKey, true);
        ov.remove();
    };
    closeBtn.onclick = close;
    foot.appendChild(closeBtn);
    card.appendChild(foot);
    document.addEventListener('keydown', onKey, true);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) close(); });
    ov.appendChild(card);
    document.body.appendChild(ov);

    let scope = 'board';
    let query = '';
    let seq = 0;
    const syncTabs = () => {
        boardBtn.classList.toggle('on', scope === 'board');
        allBtn.classList.toggle('on', scope === 'all');
    };
    const load = async () => {
        const my = ++seq;
        list.textContent = '';
        try {
            const q = scope === 'board'
                ? `?board_id=${encodeURIComponent(state.currentBoard || '')}&limit=50`
                : '?limit=50';
            const j = await fetchJSON(`/api/backtest/optimizations${q}`);
            if (my !== seq) return;
            paint(j.optimizations || []);
        } catch (e) {
            if (my === seq) list.appendChild(el('div', 'bt-err', e.message));
        }
    };
    const paint = (rows) => {
        list.textContent = '';
        const q = query.trim().toLowerCase();
        const filtered = rows.filter(row0 => !q || [
            row0.job_id, row0.board_id, row0.mode, row0.method, row0.status,
            row0.best_params && Object.entries(row0.best_params)
                .map(([k, v]) => `${k}=${v}`).join(' '),
        ].filter(Boolean).join(' ').toLowerCase().includes(q));
        if (!filtered.length) {
            list.appendChild(el('div', 'bt-hint',
                query.trim() ? t('bt.opt.history_no_match') : t('bt.opt.history_empty')));
            return;
        }
        filtered.forEach(row0 => {
            const b = el('div', 'bt-opt-history-row');
            b.tabIndex = 0;
            b.setAttribute('role', 'button');
            b.title = `${row0.job_id}${row0.script ? ` · ${row0.script}` : ''}`;
            const mode = row0.mode === 'walk_forward'
                ? 'WF' : t('bt.opt.history_mode_single');
            const best = Object.entries(row0.best_params || {})
                .map(([k, v]) => `${k}=${v}`).join(' ') || '—';
            const method = (row0.optimizer && row0.optimizer.name) || row0.method || '';
            const status = row0.status && row0.status !== 'done'
                ? ` · ${row0.status}` : '';
            const symbol = row0.symbol || row0.board_name || row0.board_id
                || t('bt.opt.history_unknown_symbol');
            const strategy = row0.strategy_name
                || (row0.script ? String(row0.script).split('/').pop() : '')
                || t('bt.opt.history_unknown_strategy');
            const main = el('div', 'bt-opt-history-main');
            const title = el('div', 'bt-opt-history-title');
            title.append(el('span', 'bt-opt-history-symbol', symbol),
                         el('span', 'bt-opt-history-strategy', strategy));
            const sub = el('div', 'bt-opt-history-sub',
                [row0.timeframe, mode, method + status, best]
                    .filter(Boolean).join(' · '));
            main.append(title, sub);
            const time = el('span', 'bt-opt-history-time',
                new Date((row0.finished_at || row0.created_at || 0) * 1000)
                    .toLocaleString());
            const actions = el('span', 'bt-opt-history-actions');
            const del = el('button', 'btn-ghost bt-opt-history-del',
                           t('bt.opt.history_delete'));
            del.type = 'button';
            del.onclick = async (ev) => {
                ev.stopPropagation();
                const yes = await openDialog({
                    title: t('bt.opt.history_delete_title'),
                    message: t('bt.opt.history_delete_confirm', { job: row0.job_id }),
                    confirmText: t('bt.opt.history_delete'),
                    danger: true,
                });
                if (!yes) return;
                try {
                    await fetchJSON(
                        `/api/backtest/optimizations/${encodeURIComponent(row0.job_id)}`,
                        { method: 'DELETE' });
                    toast(t('bt.opt.history_deleted'));
                    await load();
                } catch (e) {
                    toast(`${t('bt.opt.history_delete_fail')}: ${e.message}`);
                }
            };
            actions.appendChild(del);
            b.append(main, time, actions);
            const open = async () => {
                try {
                    const st = await fetchJSON(`/api/backtest/optimize/${row0.job_id}`);
                    close();
                    openOptimizeReport(st);
                } catch (e) { toast(e.message); }
            };
            b.onclick = open;
            b.onkeydown = (ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); }
            };
            list.appendChild(b);
        });
    };
    boardBtn.onclick = () => { scope = 'board'; syncTabs(); load(); };
    allBtn.onclick = () => { scope = 'all'; syncTabs(); load(); };
    search.addEventListener('input', () => { query = search.value; load(); });
    syncTabs();
    await load();
};
const openOptimizeReport = (st) => {
    if (document.getElementById('bt-opt-report-overlay')) return;
    const ov = el('div', 'overlay dialog-overlay');
    ov.id = 'bt-opt-report-overlay';
    const card = el('div', 'overlay-card dialog-card bt-opt-report');
    card.appendChild(el('h3', '', t('bt.opt.report')));
    const metricKey = (st.objective && st.objective.metric) || 'sharpe';
    const metricLabel = t(`bt.opt.metric.${metricKey}`);
    const best = st.best;
    const optName = (st.optimizer && st.optimizer.name) || st.method;
    const optSrc = st.optimizer && st.optimizer.source === 'custom'
        ? ` · ${t('bt.opt.custom')}` : '';
    const opKeys = Object.keys(st.optimizer_params || {});
    const opStr = opKeys.length
        ? `${t('bt.opt.params')}: ${fmtParams(st.optimizer_params)}` : '';
    const wf = st.walk_forward || {};
    const sum = wf.summary || {};
    const folds = st.folds || [];
    const stab = st.stability;
    const valid = sum.valid_folds ?? folds.filter(f => f.oos_stats).length;
    const pos = sum.positive_folds ?? folds.filter(f =>
        Number((f.oos_stats || {}).total_return || 0) > 0).length;
    const neg = sum.negative_folds ?? folds.filter(f =>
        Number((f.oos_stats || {}).total_return || 0) < 0).length;
    const flat = sum.flat_folds ?? Math.max(0, valid - pos - neg);
    const wfe = sum.wfe;
    const pass = stab ? Number(stab.pass_ratio || 0) : null;
    const isolated = !!(stab && stab.isolated_peak);
    const warnCodes = new Set((st.warnings || []).map(w => w.code));
    const centerOos = Number((((stab || {}).center || {}).oos_stats || {})[metricKey]);
    const stabEdge = !stab || metricKey === 'max_drawdown' ||
        (Number.isFinite(centerOos) && centerOos > 0);
    const fmtPct = (v) => {
        if (v == null || v === '') return '—';
        const n = Number(v);
        return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : '—';
    };
    const fmtInt = (v) => (v == null || v === '' ? '—' : String(v));
    const passText = stab ? (stabEdge ? fmtPct(pass) : t('bt.opt.stab_no_edge')) : '—';
    const passDisplay = stabEdge ? fmtPct(pass) : '—';

    const meta = el('div', 'bt-report-meta');
    meta.append(
        el('span', 'bt-report-badge', st.mode === 'walk_forward' ? 'WF' : 'Single'),
        el('span', '', `${optName}${optSrc}`),
        el('span', '', metricLabel),
        el('span', '', `${((st.elapsed_ms || 0) / 1000).toFixed(1)}s`),
    );
    if (opStr) meta.append(el('span', '', opStr));
    meta.title = st.seed != null ? `seed=${st.seed}` : '';
    card.appendChild(meta);

    let tone = 'caution';
    const oosRisk = warnCodes.has('OOS_NO_EDGE') || warnCodes.has('OOS_DEGRADED') ||
        warnCodes.has('WF_FOLD_NEGATIVE') || warnCodes.has('WF_DEGRADED');
    if (folds.length) {
        if (isolated || (wfe != null && Number(wfe) < 0) ||
            (valid && pos / valid < 0.4)) tone = 'bad';
        else if (valid && pos / valid >= 0.6 && !isolated && !oosRisk &&
                 (wfe == null || Number(wfe) >= 0.5)) tone = 'good';
    } else if (best) {
        const oosv = Number((best.oos_stats || {})[metricKey]);
        const isv = Number((best.is_stats || {})[metricKey]);
        if (isolated || warnCodes.has('OOS_NO_EDGE')) tone = 'bad';
        else if (Number.isFinite(oosv) && oosv > 0 &&
                 (!Number.isFinite(isv) || oosv >= isv * 0.5)) tone = 'good';
    }
    const verdict = el('div', `bt-report-verdict ${tone}`);
    const vhead = el('div', 'bt-report-verdict-head');
    vhead.append(
        el('span', 'bt-report-verdict-label', t(`bt.opt.verdict.${tone}`)),
        el('span', 'bt-report-verdict-line', folds.length
            ? `${pos}/${valid} ${t('bt.opt.kpi.positive')} · WFE ${fmtPct(wfe)} · ${t('bt.opt.kpi.stability')} ${passDisplay}`
            : `OOS ${metricLabel} ${fmtMetric(metricKey, (best && best.oos_stats || {})[metricKey])} · ${t('bt.opt.kpi.stability')} ${passDisplay}`),
    );
    verdict.appendChild(vhead);
    verdict.appendChild(el('div', 'bt-report-verdict-note', t(`bt.opt.verdict.${tone}_note`)));
    const drifts = Object.entries(sum.parameter_drift || {})
        .filter(([, d]) => Number((d || {}).range || 0) > 0)
        .sort((a, b) => Number((b[1] || {}).range || 0) - Number((a[1] || {}).range || 0));
    const mainDrift = drifts[0];
    const kpis = [];
    if (folds.length) {
        kpis.push([t('bt.opt.kpi.positive'), `${pos}/${valid}`],
                  [t('bt.opt.kpi.wfe'), fmtPct(wfe)],
                  [t('bt.opt.kpi.stability'), passText],
                  [t('bt.opt.kpi.drift'), mainDrift
                      ? `${mainDrift[0]} ${mainDrift[1].min}~${mainDrift[1].max}`
                      : t('bt.opt.kpi.no_drift')]);
    } else {
        kpis.push([t('bt.opt.wf_return'), fmtPct((best && best.oos_stats || {}).total_return)],
                  [t('bt.opt.metric.sharpe'), fmtMetric('sharpe', (best && best.oos_stats || {}).sharpe)],
                  [t('bt.opt.kpi.stability'), passText],
                  [t('bt.opt.wf_trades'), fmtInt((best && best.oos_stats || {}).trade_count)]);
    }
    const kpiBox = el('div', 'bt-report-kpis');
    kpis.forEach(([k, v]) => {
        const item = el('div', 'bt-report-kpi');
        item.append(el('b', '', v), el('span', '', k));
        kpiBox.appendChild(item);
    });
    verdict.appendChild(kpiBox);
    card.appendChild(verdict);

    if (best) {
        const box = el('div', 'bt-opt-best bt-report-best');
        box.appendChild(el('div', 'bt-opt-best-title',
            st.mode === 'walk_forward' ? t('bt.opt.best_wf') : t('bt.opt.best')));
        box.appendChild(el('div', 'bt-opt-best-params mono', fmtParams(best.params)));
        const oos = best.oos_stats || {};
        const oosBits = [];
        if (oos.total_return != null) oosBits.push(`${t('bt.opt.wf_return')} ${fmtPct(oos.total_return)}`);
        if (oos.sharpe != null) oosBits.push(`${t('bt.opt.metric.sharpe')} ${fmtMetric('sharpe', oos.sharpe)}`);
        if (oos.trade_count != null) oosBits.push(`${t('bt.opt.wf_trades')} ${oos.trade_count}`);
        if (oosBits.length) box.appendChild(el('div', 'bt-report-best-oos', oosBits.join(' · ')));
        card.appendChild(box);
        const acts = el('div', 'bt-opt-acts');
        if (best.result_id) {
            const view = el('button', 'btn-primary', t('bt.opt.view_result'));
            view.type = 'button';
            view.onclick = () => {
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
    } else {
        card.appendChild(el('div', 'bt-opt-empty', t('bt.opt.no_best')));
    }

    if (folds.length) {
        const sec = el('section', 'bt-report-section bt-wf-section');
        const head = el('div', 'bt-report-section-head');
        head.append(el('div', 'bt-report-section-title', t('bt.opt.wf_title')),
                    el('span', 'bt-report-chip', `${folds.length} ${t('bt.opt.fold')}`));
        sec.appendChild(head);
        const timeline = el('div', 'bt-wf-timeline');
        folds.forEach((f, i) => {
            const ret = Number((f.oos_stats || {}).total_return || 0);
            const kind = ret > 0 ? 'good' : ret < 0 ? 'bad' : 'flat';
            const seg = el('div', `bt-wf-seg ${kind}`);
            seg.style.flexGrow = String(Math.max(1, Number(f.oos_bars) || 1));
            seg.title = `${t('bt.opt.fold')} ${i + 1}: ${fmtShortDate(f.oos_start)} → ${fmtShortDate(f.oos_end)}`;
            seg.append(el('span', 'bt-wf-seg-i', String(i + 1)),
                       el('span', 'bt-wf-seg-v', fmtPct(ret)));
            timeline.appendChild(seg);
        });
        sec.appendChild(el('div', 'bt-report-subtitle', t('bt.opt.wf_timeline')));
        sec.appendChild(timeline);

        const tbl = el('table', 'bt-opt-wf-table');
        const trh = document.createElement('tr');
        [t('bt.opt.fold'), t('bt.opt.wf_oos_range'), t('bt.opt.params'),
         t('bt.opt.wf_is_return'), t('bt.opt.wf_return'), t('bt.opt.wf_sharpe'),
         t('bt.opt.wf_trades'), ''].forEach(h => {
            trh.appendChild(el('th', '', h));
        });
        tbl.appendChild(trh);
        folds.forEach((f, i) => {
            const tr = document.createElement('tr');
            const ret = Number((f.oos_stats || {}).total_return);
            tr.appendChild(el('td', 'bt-wf-fold', `${i + 1}`));
            tr.appendChild(el('td', 'bt-wf-date',
                `${fmtShortDate(f.oos_start)} → ${fmtShortDate(f.oos_end)}`));
            tr.appendChild(el('td', 'mono', fmtParams(f.params)));
            const isRet = Number((f.is_stats || {}).total_return);
            const oosRet = Number((f.oos_stats || {}).total_return);
            tr.appendChild(el('td', 'bt-wf-is-ret', fmtPct(isRet)));
            tr.appendChild(el('td', `bt-wf-oos-ret ${oosRet > 0 ? 'up' : oosRet < 0 ? 'down' : 'flat'}`,
                fmtPct(oosRet)));
            tr.appendChild(el('td', '',
                `${fmtMetric('sharpe', (f.is_stats || {}).sharpe)} → ${fmtMetric('sharpe', (f.oos_stats || {}).sharpe)}`));
            tr.appendChild(el('td', '', fmtInt((f.oos_stats || {}).trade_count)));
            const act = el('td', '');
            if (f.result_id) {
                const v = el('button', 'btn-ghost', t('bt.opt.view_oos'));
                v.type = 'button';
                v.onclick = () => { ov.remove(); try { focusResult(f.result_id); } catch (e) {} };
                act.appendChild(v);
            }
            tr.appendChild(act);
            tbl.appendChild(tr);
        });
        sec.appendChild(tbl);
        card.appendChild(sec);
    }

    if (stab && stab.runs) {
        const sec = el('section', 'bt-report-section bt-stab-section');
        const chips = el('div', 'bt-report-chips');
        chips.append(
            el('span', 'bt-report-chip', `${t('bt.opt.stab_pass')} ${passDisplay}`),
            el('span', 'bt-report-chip', `${t('bt.opt.stab_plateau')} ${stabEdge ? fmtPct(stab.plateau_ratio) : '—'}`),
            el('span', `bt-report-chip ${isolated ? 'bad' : 'good'}`,
               `${t('bt.opt.stab_peak')} ${isolated ? t('bt.opt.stab_yes') : t('bt.opt.stab_no')}`),
        );
        if (!stabEdge) chips.appendChild(el('span', 'bt-report-chip bad', t('bt.opt.stab_no_edge')));
        const head = el('div', 'bt-report-section-head');
        head.append(el('div', 'bt-report-section-title', t('bt.opt.stability_title')), chips);
        sec.appendChild(head);
        if (stabEdge) {
            sec.appendChild(el('div', 'bt-report-axis-note',
                t('bt.opt.stab_axis_hint', { metric: metricLabel })));
        }

        const center = (stab.center && stab.center.params) || {};
        const keys = Object.keys(center);
        const runs = (stab.runs || []).filter(r => r.status === 'ok' && r.oos_stats);
        let axes = 0;
        if (!stabEdge) {
            sec.appendChild(el('div', 'bt-hint', t('bt.opt.stab_no_edge_hint')));
        }
        if (stabEdge) keys.forEach(key => {
            const rows = runs.filter(r => keys.every(k =>
                k === key || r.params[k] === center[k]));
            if (rows.length < 2) return;
            rows.sort((a, b) => {
                const av = a.params[key], bv = b.params[key];
                return typeof av === 'number' && typeof bv === 'number'
                    ? av - bv : String(av).localeCompare(String(bv));
            });
            const maxAbs = Math.max(...rows.map(r =>
                Math.abs(Number((r.oos_stats || {})[metricKey]) || 0)), 1e-9);
            const axis = el('div', 'bt-stab-axis');
            const ah = el('div', 'bt-stab-axis-head');
            ah.append(el('b', '', key),
                      el('span', '', `${t('bt.opt.stab_center')} ${center[key]}`));
            axis.appendChild(ah);
            rows.forEach(r => {
                const v = Number((r.oos_stats || {})[metricKey]);
                if (!Number.isFinite(v)) return;
                const isCenter = !!r.center;
                const row = el('div', `bt-stab-row${isCenter ? ' center' : ''}`);
                row.appendChild(el('span', 'bt-stab-k', String(r.params[key])));
                const track = el('div', 'bt-stab-track');
                const bar = el('i', `bt-stab-bar ${v >= 0 ? 'pos' : 'neg'}`);
                bar.style.width = `${Math.max(2, Math.abs(v) / maxAbs * 100)}%`;
                track.appendChild(bar);
                row.appendChild(track);
                row.appendChild(el('span', 'bt-stab-v', fmtMetric(metricKey, v)));
                row.title = `${fmtParams(r.params)} · IS ${fmtMetric(metricKey,
                    (r.is_stats || {})[metricKey])}`;
                axis.appendChild(row);
            });
            sec.appendChild(axis);
            axes++;
        });
        if (stabEdge && !axes) {
            sec.appendChild(el('div', 'bt-hint', t('bt.opt.stab_details')));
        }

        if (runs.length) {
            const det = document.createElement('details');
            det.className = 'bt-report-details';
            const dsum = document.createElement('summary');
            dsum.textContent = `${t('bt.opt.stab_details')} (${runs.length})`;
            det.appendChild(dsum);
            const tbl = el('table', 'bt-stab-table');
            const trh = document.createElement('tr');
            [t('bt.opt.params'), 'IS', 'OOS', ''].forEach(h => trh.appendChild(el('th', '', h)));
            tbl.appendChild(trh);
            runs.forEach(r => {
                const tr = document.createElement('tr');
                if (r.center) tr.classList.add('center');
                tr.appendChild(el('td', 'mono', fmtParams(r.params)));
                tr.appendChild(el('td', '', fmtMetric(metricKey, r.is_value)));
                tr.appendChild(el('td', '', fmtMetric(metricKey, r.oos_value)));
                tr.appendChild(el('td', '', r.status === 'ok' ? '' : (r.reason || r.status)));
                tbl.appendChild(tr);
            });
            det.appendChild(tbl);
            sec.appendChild(det);
        }
        card.appendChild(sec);
    }

    const warns = (st.warnings || []).filter(w =>
        ['OOS_DEGRADED', 'OOS_NO_EDGE', 'OOS_INVALID', 'NO_OOS_VALID',
         'NO_HOLDOUT', 'TIME_BUDGET', 'NO_VALID_TRIAL', 'WF_FOLD_NEGATIVE',
         'WF_DEGRADED', 'WF_PARAM_DRIFT', 'WF_FOLDS_REDUCED', 'WF_INSUFFICIENT_BARS',
         'PARAM_ISOLATED_PEAK', 'STABILITY_FEW_RUNS',
         'STABILITY_NO_CENTER', 'STABILITY_UNSUPPORTED_MULTI'].includes(w.code));
    if (warns.length) {
        const sec = el('section', 'bt-report-section');
        sec.appendChild(el('div', 'bt-report-section-title', t('bt.opt.risk')));
        const box = el('div', 'bt-report-risks');
        warns.slice(0, 8).forEach(w => {
            const where = w.fold != null
                ? `${t('bt.opt.fold')} ${w.fold + 1} · `
                : (w.phase === 'stability' ? `${t('bt.opt.stability_title')} · ` : '');
            box.appendChild(el('div', 'bt-report-risk', `⚠ ${where}${w.message || w.code}`));
        });
        sec.appendChild(box);
        card.appendChild(sec);
    } else {
        card.appendChild(el('div', 'bt-report-ok', `✓ ${t('bt.opt.no_warnings')}`));
    }

    if (best) {
        const det = document.createElement('details');
        det.className = 'bt-report-details';
        const dsum = document.createElement('summary');
        dsum.textContent = t('bt.opt.metrics_details');
        det.appendChild(dsum);
        const tbl = el('table', 'bt-opt-metrics');
        const trh = document.createElement('tr');
        [t('bt.opt.metric'), 'IS', 'OOS'].forEach(h => trh.appendChild(el('th', '', h)));
        tbl.appendChild(trh);
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
                ? fmtInt(isv) : fmtMetric(k, isv)));
            tr.appendChild(el('td', '', k === 'trade_count'
                ? fmtInt(oosv) : fmtMetric(k, oosv)));
            tbl.appendChild(tr);
        });
        det.appendChild(tbl);
        card.appendChild(det);
    }

    const trialRows = [...(st.trials || [])].sort((a, b) => {
        const sa = a.oos_score ?? a.score;
        const sb = b.oos_score ?? b.score;
        return (sb == null ? -Infinity : sb) - (sa == null ? -Infinity : sa);
    });
    if (trialRows.length) {
        const det = document.createElement('details');
        det.className = 'bt-report-details';
        const dsum = document.createElement('summary');
        dsum.textContent = `${t('bt.opt.trials_details')} (${trialRows.length})`;
        det.appendChild(dsum);
        const wrap = el('div', 'bt-opt-trials');
        const tbl = el('table', 'bt-opt-trial-table');
        const thead = document.createElement('tr');
        const hasFold = trialRows.some(t => t.fold != null);
        ['#', ...(hasFold ? [t('bt.opt.fold')] : []), t('bt.opt.params'), t('bt.opt.status'),
         'IS', 'OOS', ''].forEach(h => thead.appendChild(el('th', '', h)));
        tbl.appendChild(thead);
        trialRows.slice(0, 200).forEach(tr0 => {
            const tr = document.createElement('tr');
            tr.appendChild(el('td', '', String((tr0.index ?? 0) + 1)));
            if (hasFold) tr.appendChild(el('td', '', tr0.fold == null ? '—' : String(tr0.fold + 1)));
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
                v.onclick = () => {
                    ov.remove();
                    try { focusResult(tr0.result_id); } catch (e) { /* 结果已淘汰 */ }
                };
                act.appendChild(v);
            }
            tr.appendChild(act);
            tbl.appendChild(tr);
        });
        wrap.appendChild(tbl);
        det.appendChild(wrap);
        card.appendChild(det);
    }

    const foot = el('div', 'dialog-foot');
    const savedHint = el('span', 'bt-opt-saved-hint', t('bt.opt.report_saved'));
    const paperBest = el('button', 'btn-ghost', t('result.create_paper'));
    paperBest.type = 'button';
    paperBest.onclick = () => {
        ov.remove();
        window.dispatchEvent(new CustomEvent('ak:paper-create', {
            detail: {
                script: st.script || '',
                params: (best && best.params) || st.best_params || {},
                timeframe: st.timeframe || '',
            },
        }));
    };
    if (!(best && (best.params || st.best_params)) && !st.script) paperBest.style.display = 'none';
    const hist = el('button', 'btn-ghost', t('bt.opt.history'));
    hist.type = 'button';
    hist.onclick = () => { ov.remove(); openOptimizeHistory(); };
    const closeBtn = el('button', 'btn-primary', t('common.close'));
    closeBtn.type = 'button';
    closeBtn.onclick = () => ov.remove();
    foot.append(savedHint, paperBest, hist, closeBtn);
    card.appendChild(foot);
    const onKey = (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); ov.remove(); }
    };
    document.addEventListener('keydown', onKey, true);
    ov.addEventListener('mousedown', (e) => { if (e.target === ov) ov.remove(); });
    ov.appendChild(card);
    document.body.appendChild(ov);
};

export async function openBacktestDialog(opts = {}) {
    if (document.getElementById('bt-overlay')) return;
    let engines = [];
    let strategies = [];
    let optimizers = [];
    let presets = [];
    try {
        [engines, strategies] = await Promise.all([loadEngines(), loadStrategies()]);
    } catch (e) {
        toast(`${t('bt.load_fail')}: ${e.message}`);
        return;
    }
    try {
        optimizers = (await fetchJSON('/api/optimizers')).optimizers || [];
    } catch (e) { optimizers = []; }
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

    // v0.6.6 两段式：① 引擎参数（怎么跑）② 策略参数（跑什么）
    const engineGroup = el('div', 'bt-group');
    const stratGroup = el('div', 'bt-group');
    bodyBox.append(engineGroup, stratGroup);

    // 运行方式：单次 / 参数寻优（参数矩阵已并入寻优的 grid，不再单独存在）
    let mode = 'single';
    const tabSingle = el('button', 'bt-mode on', t('bt.tab.single'));
    const tabOptimize = el('button', 'bt-mode', t('bt.tab.optimize'));
    tabSingle.type = tabOptimize.type = 'button';

    // 引擎
    const engineSel = document.createElement('select');
    engineSel.id = 'bt-engine';
    engines.forEach(e => {
        const o = document.createElement('option');
        o.value = e.id;
        o.textContent = `${e.id} ${e.version || ''}`.trim();
        engineSel.appendChild(o);
    });
    engineGroup.appendChild(groupHead(1, t('bt.group.engine'), t('bt.group.engine_sub')));
    engineGroup.appendChild(row(t('bt.engine'), engineSel));

    // 策略
    const stratSel = document.createElement('select');
    stratSel.id = 'bt-strategy';
    strategies.forEach(s => {
        const o = document.createElement('option');
        o.value = s.id;
        o.textContent = `${s.display || s.id}`;
        o.title = s.desc || s.id;
        stratSel.appendChild(o);
    });
    const stratRow = row(t('bt.strategy'), stratSel,
        strategies.length ? '' : t('bt.no_strategy'));
    stratGroup.appendChild(groupHead(2, t('bt.group.strategy'), t('bt.group.strategy_sub')));
    stratGroup.appendChild(stratRow);
    const strategyMeta = el('div', 'bt-strategy-meta');
    stratGroup.appendChild(strategyMeta);
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
    stratGroup.appendChild(row(t('bt.preset'), presetWrap,
        t('bt.preset_hint')));
    const pasteHint = el('div', 'bt-hint');
    pasteHint.style.display = 'none';
    stratGroup.appendChild(pasteHint);

    // 运行方式放在策略区内：选策略 → 套方案 → 选运行方式 → 调参数
    const modesWrap = el('div', 'bt-modes');
    modesWrap.append(tabSingle, tabOptimize);
    stratGroup.appendChild(row(t('bt.mode'), modesWrap));
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
        updateOptimizeDefaults();
        refreshSummary();
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
        refreshSummary();
        updateOptimizeDefaults();
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
            const pp = el('button', 'btn-ghost', t('result.create_paper'));
            pp.type = 'button';
            pp.onclick = () => {
                closeOv();
                window.dispatchEvent(new CustomEvent('ak:paper-create', {
                    detail: { script: p.script, params: p.params || {},
                              timeframe: p.timeframe || '' },
                }));
            };
            acts.appendChild(pp);
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
    dirSel.id = 'bt-direction';
    [['long_only', t('bt.dir.long_only')],
     ['short_only', t('bt.dir.short_only')],
     ['both', t('bt.dir.both')]].forEach(([v, label]) => {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = label;
        dirSel.appendChild(o);
    });
    dirSel.value = 'long_only';
    engineGroup.appendChild(row(t('bt.direction'), dirSel, t('bt.direction_hint')));

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
    engineGroup.appendChild(row(t('bt.range'), rangeBox, t('bt.range_hint')));

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
    const costWrap = el('div', 'bt-triple');
    const costCell = (label, ctl) => {
        const c = el('label', 'bt-pair-cell');
        c.appendChild(el('span', '', label));
        c.appendChild(ctl);
        return c;
    };
    costWrap.append(
        costCell(t('bt.cash'), cash),
        costCell(`${t('bt.fee')} (bp)`, fee),
        costCell(`${t('bt.slip')} (bp)`, slip),
    );
    engineGroup.appendChild(row(t('bt.cost'), costWrap, t('bt.cost_hint')));

    // 策略参数（按策略声明动态渲染）
    const paramsHead = subHead(t('bt.params_block'));
    stratGroup.appendChild(paramsHead);
    const paramsBox = el('div', 'bt-params');
    stratGroup.appendChild(paramsBox);

    // 参数寻优表单（运行方式=寻优时出现）；放在保护之前，寻优时先看到搜索设置
    const optimizeBox = el('div', 'bt-optimize');
    optimizeBox.style.display = 'none';
    stratGroup.appendChild(optimizeBox);

    // 保护（可选，按百分比输入；PROTECTION 属于策略契约，留在策略区）
    stratGroup.appendChild(subHead(t('bt.protect')));
    const sl = numInput(null, { min: 0, max: 99, step: '0.1', placeholder: t('bt.off') });
    const tp = numInput(null, { min: 0, max: 999, step: '0.1', placeholder: t('bt.off') });
    stratGroup.appendChild(row(t('bt.stop'), sl, t('bt.stop_hint')));
    stratGroup.appendChild(row(t('bt.take'), tp));

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
    const summary = el('div', 'bt-summary');
    card.appendChild(prog);
    card.appendChild(errBox);
    card.appendChild(summary);
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
        strategyMeta.textContent = '';
        meta = null;
        if (!stratSel.value) return;
        fetchJSON(`/api/strategy/meta?script=${encodeURIComponent(stratSel.value)}`)
            .then(j => {
                meta = j;
                if (j.error) { errBox.textContent = j.error; return; }
                strategyMeta.textContent = '';
                const desc = el('div', 'bt-meta');
                const bits = [];
                if (j.name) bits.push(j.name);
                if (j.warmup != null) bits.push(`WARMUP ${j.warmup}`);
                if (j.bars_per_year) bits.push(`${j.bars_per_year}/yr`);
                desc.textContent = bits.join(' · ');
                strategyMeta.appendChild(desc);
                if (j.desc) strategyMeta.appendChild(el('div', 'bt-hint', j.desc));
                if (j.errors && j.errors.length) {
                    const e = j.errors[0];
                    errBox.textContent = `${e.code}: ${e.message}`;
                }
                paintOptimize(j);
                const params = j.params || {};
                const metaMap = j.param_meta || {};
                const keys = Object.keys(params);
                if (keys.length) {
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
                updateOptimizeDefaults();
                refreshSummary();
            })
            .catch(e => { errBox.textContent = `meta: ${e.message}`; });
    };
    // ---- v0.6.5 参数寻优：空间/目标/约束/预算/样本外 ----
    const OPT_METRICS = ['total_return', 'annual_return', 'sharpe', 'sortino',
                         'calmar', 'max_drawdown', 'profit_factor', 'win_rate'];
    const currentParamValues = () => ({
        ...((meta && meta.params) || {}),
        ...(pendingParams || {}),
        ...readParams(paramsBox),
    });
    let optParamsBox = null;
    let lastOptimizerId = 'optimizer/grid';
    const renderOptimizerParams = (id) => {
        if (!optParamsBox) return;
        optParamsBox.textContent = '';
        const o = optimizers.find(x => x.id === id);
        const params = (o && o.params) || {};
        const pmeta = (o && o.param_meta) || {};
        const keys = Object.keys(params);
        if (!keys.length) {
            optParamsBox.style.display = 'none';
            return;
        }
        optParamsBox.style.display = '';
        optParamsBox.appendChild(subHead(t('bt.opt.params')));
        keys.forEach(k => {
            const ctl = paramControl(k, params[k], pmeta[k]);
            ctl.dataset.pname = k;
            ctl.dataset.opname = k;
            const label = (pmeta[k] && pmeta[k].label) || k;
            optParamsBox.appendChild(row(label, ctl,
                pmeta[k] && pmeta[k].min != null
                    ? `${pmeta[k].min} ~ ${pmeta[k].max ?? '∞'}` : ''));
        });
    };
    const readOptimizerParams = () => (optParamsBox ? readParams(optParamsBox) : {});
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
        if (optimizers.length) {
            optimizers.forEach(item => {
                const o = document.createElement('option');
                o.value = item.id;
                o.textContent = `${item.name}${item.source === 'custom'
                    ? ` · ${t('bt.opt.custom')}` : ''}`;
                o.title = item.desc || item.id;
                method.appendChild(o);
            });
            method.value = optimizers.some(x => x.id === lastOptimizerId)
                ? lastOptimizerId : optimizers[0].id;
        } else {
            const o = document.createElement('option');
            o.value = '';
            o.textContent = t('bt.opt.no_optimizer');
            method.appendChild(o);
            method.disabled = true;
        }
        lastOptimizerId = method.value;
        method.onchange = () => {
            lastOptimizerId = method.value;
            renderOptimizerParams(method.value);
            refreshSummary();
        };
        const optMode = document.createElement('select');
        optMode.id = 'bt-opt-mode';
        [['single', t('bt.opt.mode.single')],
         ['walk_forward', t('bt.opt.mode.walk_forward')]].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            optMode.appendChild(o);
        });
        optMode.value = 'single';
        optimizeBox.appendChild(row(t('bt.opt.mode'), optMode, t('bt.opt.mode_hint')));

        optimizeBox.appendChild(row(t('bt.opt.method'), method, t('bt.opt.method_hint')));
        optParamsBox = el('div', 'bt-opt-params');
        optimizeBox.appendChild(optParamsBox);
        renderOptimizerParams(method.value);

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
        const holdRow = row(t('bt.opt.holdout'), holdWrap, t('bt.opt.holdout_hint'));
        optimizeBox.appendChild(holdRow);

        const wfFolds = numInput(5, { min: 3, max: 10, step: 1 });
        wfFolds.id = 'bt-opt-wf-folds';
        const wfWindow = document.createElement('select');
        wfWindow.id = 'bt-opt-wf-window';
        [['rolling', t('bt.opt.wf.rolling')],
         ['anchored', t('bt.opt.wf.anchored')]].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            wfWindow.appendChild(o);
        });
        const wfRatio = document.createElement('select');
        wfRatio.id = 'bt-opt-wf-ratio';
        [['0.75', '3:1 (75%)'], ['0.8', '4:1 (80%)'], ['0.667', '2:1 (67%)']]
            .forEach(([v, label]) => {
                const o = document.createElement('option');
                o.value = v;
                o.textContent = label;
                wfRatio.appendChild(o);
            });
        const wfWrap = el('div', 'bt-inline');
        wfWrap.append(wfFolds, wfWindow, wfRatio);
        const wfRow = row(t('bt.opt.wf'), wfWrap, t('bt.opt.wf_hint'));
        wfRow.style.display = 'none';
        optimizeBox.appendChild(wfRow);

        const stab = document.createElement('input');
        stab.type = 'checkbox';
        stab.id = 'bt-opt-stability';
        stab.checked = true;
        let stabTouched = false;
        stab.addEventListener('change', () => { stabTouched = true; });
        const stabMode = document.createElement('select');
        stabMode.id = 'bt-opt-stab-mode';
        [['auto', t('bt.opt.stab.mode.auto')],
         ['step', t('bt.opt.stab.mode.step')],
         ['percent', t('bt.opt.stab.mode.percent')]].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            stabMode.appendChild(o);
        });
        const stabRadius = document.createElement('select');
        stabRadius.id = 'bt-opt-stab-radius';
        [['1', '±1'], ['2', '±2']].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            stabRadius.appendChild(o);
        });
        const stabScope = document.createElement('select');
        stabScope.id = 'bt-opt-stab-scope';
        [['one_at_a_time', t('bt.opt.stab.scope.one_at_a_time')],
         ['top2', t('bt.opt.stab.scope.top2')],
         ['full', t('bt.opt.stab.scope.full')]].forEach(([v, label]) => {
            const o = document.createElement('option');
            o.value = v;
            o.textContent = label;
            stabScope.appendChild(o);
        });
        const stabField = (label, ctl) => {
            const w = el('label', 'bt-opt-mini');
            w.appendChild(el('span', '', label));
            w.appendChild(ctl);
            return w;
        };
        const stabWrap = el('div', 'bt-inline');
        stabWrap.append(
            stabField(t('bt.opt.stab_on'), stab),
            stabField(t('bt.opt.stab_mode'), stabMode),
            stabField(t('bt.opt.stab_radius'), stabRadius),
            stabField(t('bt.opt.stab_scope'), stabScope),
        );
        optimizeBox.appendChild(row(t('bt.opt.stability'), stabWrap,
                                    t('bt.opt.stability_hint')));

        const updateOptMode = () => {
            const wf = optMode.value === 'walk_forward';
            holdRow.style.display = wf ? 'none' : '';
            wfRow.style.display = wf ? '' : 'none';
            if (!stabTouched) stab.checked = !wf;
            refreshSummary();
        };
        optMode.onchange = updateOptMode;

        optimizeBox.appendChild(el('div', 'bt-sec', t('bt.opt.space')));
        optimizeBox.appendChild(el('div', 'bt-hint', t('bt.opt.space_hint')));
        if (!numeric.length) {
            optimizeBox.appendChild(el('div', 'bt-hint', t('bt.opt.no_numeric')));
        }
        const cur = currentParamValues();
        numeric.forEach(k => {
            const m = metaMap[k] || {};
            const box = el('div', 'bt-space');
            box.dataset.osk = k;
            const bound = m.min != null ? `${m.min} ~ ${m.max ?? '∞'}` : '';
            box.appendChild(el('div', 'bt-space-head',
                `${m.label || k}${bound ? ` (${bound})` : ''} · ${t('bt.opt.default')}=${cur[k] ?? params[k]}`));
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

    // 方案/参数变化后，刷新寻优空间里的“默认=x”标签（不重建输入，避免丢用户已填范围）
    const updateOptimizeDefaults = () => {
        if (!meta || !optimizeBox) return;
        const cur = currentParamValues();
        optimizeBox.querySelectorAll('[data-osk]').forEach(box => {
            const k = box.dataset.osk;
            const m = ((meta && meta.param_meta) || {})[k] || {};
            const head = box.querySelector('.bt-space-head');
            if (!head) return;
            const bound = m.min != null ? `${m.min} ~ ${m.max ?? '∞'}` : '';
            head.textContent = `${m.label || k}${bound ? ` (${bound})` : ''}`
                + ` · ${t('bt.opt.default')}=${cur[k] ?? ((meta.params || {})[k])}`;
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

    const refreshSummary = () => {
        if (!summary) return;
        const scriptName = (stratSel.options[stratSel.selectedIndex] || {}).textContent || '—';
        const p = readParams(paramsBox);
        const pstr = Object.entries(p).map(([k, v]) => `${k}=${v}`).join(' ');
        const modeText = mode === 'optimize' ? t('bt.tab.optimize') : t('bt.tab.single');
        let budget = '';
        if (mode === 'optimize') {
            const runs = document.getElementById('bt-opt-runs');
            if (runs && runs.value) budget = ` · ${t('bt.summary.runs', { n: runs.value })}`;
        }
        summary.textContent = `${t('bt.summary_prefix')}: ${modeText}${budget}`
            + ` · ${scriptName}${pstr ? ` · ${pstr}` : ''}`
            + ` · ${cash.value || '—'} / ${fee.value || '0'}bp`;
    };

    const runLabel = () => (mode === 'optimize' ? t('bt.run_optimize') : t('bt.run'));
    const setMode = (m) => {
        mode = m;
        tabSingle.classList.toggle('on', m === 'single');
        tabOptimize.classList.toggle('on', m === 'optimize');
        paramsHead.style.display = m === 'single' ? '' : 'none';
        paramsBox.style.display = m === 'single' ? '' : 'none';
        optimizeBox.style.display = m === 'optimize' ? '' : 'none';
        updateOptimizeDefaults();
        run.textContent = runLabel();
        refreshSummary();
        // 切模式后把对应表单带到可视区（引擎段较长，避免切了寻优却看不到表单）
        const target = m === 'optimize' ? optimizeBox : paramsHead;
        requestAnimationFrame(() => {
            const br = bodyBox.getBoundingClientRect();
            const tr = target.getBoundingClientRect();
            bodyBox.scrollTop += (tr.top - br.top) - 8;
        });
    };
    tabSingle.onclick = () => setMode('single');
    tabOptimize.onclick = () => setMode('optimize');

    stratSel.addEventListener('change', () => {
        pendingParams = null;
        paintPresets();
        paintParams();
        refreshSummary();
    });
    if (strategies.length) paintParams();
    bodyBox.addEventListener('input', () => { refreshSummary(); updateOptimizeDefaults(); });
    bodyBox.addEventListener('change', () => { refreshSummary(); updateOptimizeDefaults(); });
    refreshSummary();

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
        const optMode = (document.getElementById('bt-opt-mode') || {}).value || 'single';
        const wfFolds = parseInt((document.getElementById('bt-opt-wf-folds') || {}).value, 10) || 5;
        const wfWindow = (document.getElementById('bt-opt-wf-window') || {}).value || 'rolling';
        const wfRatio = parseFloat((document.getElementById('bt-opt-wf-ratio') || {}).value) || 0.75;
        const stabOn = !!(document.getElementById('bt-opt-stability') || {}).checked;
        const stabMode = (document.getElementById('bt-opt-stab-mode') || {}).value || 'auto';
        const stabRadius = parseInt((document.getElementById('bt-opt-stab-radius') || {}).value, 10) || 1;
        const stabScope = (document.getElementById('bt-opt-stab-scope') || {}).value || 'one_at_a_time';
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
            optimizer_params: readOptimizerParams(),
            objective: { metric, direction },
            constraints,
            budget: { max_runs: Math.max(2, Math.min(200, maxRuns)),
                      max_seconds: Math.max(10, Math.min(3600, maxSeconds)) },
            mode: optMode,
            stability: { enabled: stabOn, mode: stabMode,
                         radius: stabRadius, scope: stabScope, max_runs: 24 },
            start_time: startMs,
            end_time: endMs + dayMs - 1,
            limit: clamp(parseInt(barsIn.value, 10) || MAX_RANGE_BARS, 1, MAX_RANGE_BARS),
        };
        if (optMode === 'single') {
            body.holdout = { ratio, top_k: Math.max(1, Math.min(10, topK)) };
        } else {
            body.walk_forward = {
                folds: Math.max(3, Math.min(10, wfFolds)),
                window: wfWindow, is_ratio: wfRatio, top_k: 1,
            };
        }
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
                    const phase = st.phase === 'wf' ? t('bt.opt.phase_wf')
                        : st.phase === 'stability' ? t('bt.opt.phase_stability')
                        : st.phase === 'oos' ? t('bt.opt.phase_oos')
                        : st.phase === 'register' ? t('bt.opt.phase_register')
                        : st.phase === 'done' ? t('bt.opt.phase_done') : t('bt.opt.phase_is');
                    let done = st.phase === 'oos' ? (st.oos_done || 0) : st.done;
                    let total = st.phase === 'oos'
                        ? ((st.holdout && st.holdout.top_k) || 0) : st.total;
                    if (st.phase === 'stability') {
                        done = st.stability_done || 0;
                        total = st.stability_total || 0;
                    }
                    const fold = st.fold ? ` · ${st.fold}/${(st.walk_forward || {}).fold_count || ''}` : '';
                    const cur = st.current ? fmtParams(st.current) : '';
                    pText.textContent = `${phase}${fold} ${done}/${total}`
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
