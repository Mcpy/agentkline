// ============================================================
// 模拟盘（v0.7.1）：对账 / 分栏 / 净值曲线
// 会话列表 / 当前持仓 / 最近决策与成交 / 启动暂停恢复停止
// ============================================================
import { state } from './state.js';
import { t } from './i18n.js';
import { toast } from './search.js';
import { openDialog } from './dialog.js';

let _sessions = [];
let _active = null;
let _detail = null;
let _strategies = null;
let _creating = false;
let _bound = false;
let _timer = null;
let _loaded = false;
let _tab = 'overview';
let _equity = null;
let _reconcile = null;
let _reconcileSid = null;
let _prefill = null;
let _saveReconcileResult = false;
let _reconcileBusy = false;

const fmtMoney = (v) => {
    const n = Number(v);
    return Number.isFinite(n)
        ? n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
};
const fmtNum = (v, d = 4) => {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(d) : '—';
};
const fmtPct = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : '—';
};
const fmtTime = (ms) => {
    const n = Number(ms);
    if (!Number.isFinite(n)) return '—';
    try {
        return new Date(n).toLocaleString('zh-CN', { hour12: false });
    } catch (e) { return String(n); }
};
const statusLabel = (s) => {
    const key = `paper.status.${s}`;
    const v = t(key);
    return v === key ? (s || '—') : v;
};

function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = String(text);
    return node;
}

async function req(url, opts = {}) {
    const r = await fetch(url, { cache: 'no-store', ...opts });
    let body = null;
    try { body = await r.json(); } catch (e) { body = null; }
    if (!r.ok) {
        const detail = body && body.detail;
        const msg = (detail && (detail.error || detail.message))
            || (typeof detail === 'string' ? detail : '')
            || (body && body.error) || `HTTP ${r.status}`;
        throw new Error(msg);
    }
    if (body && body.error) throw new Error(body.error);
    return body;
}

function boardName(id) {
    const b = (state.boards || []).find(x => x.id === id);
    return b ? (b.identity_display || b.name || b.id) : (id || '—');
}

function currentPane() {
    return document.querySelector('#wb-body .wb-pane[data-pane="paper"]');
}

function paneVisible() {
    const p = currentPane();
    return !!(p && p.style.display !== 'none' && p.offsetParent !== null);
}

export function bindPaper() {
    if (_bound) return;
    _bound = true;
    const pane = currentPane();
    if (!pane) return;
    pane.addEventListener('click', (e) => {
        const act = e.target.closest('[data-paper-action]');
        if (act) {
            e.stopPropagation();
            action(act.dataset.paperAction, act.dataset.sessionId);
            return;
        }
        const tab = e.target.closest('[data-paper-tab]');
        if (tab) {
            e.stopPropagation();
            _tab = tab.dataset.paperTab || 'overview';
            renderPaper();
            return;
        }
        if (e.target.closest('#paper-new')) {
            _creating = true;
            _prefill = null;
            loadStrategies().then(renderPaper);
            return;
        }
        if (e.target.closest('#paper-cancel')) {
            _creating = false;
            _prefill = null;
            renderPaper();
            return;
        }
        if (e.target.closest('#paper-create')) {
            createSession();
            return;
        }
        const row = e.target.closest('.paper-row');
        if (row && row.dataset.sessionId) {
            _active = row.dataset.sessionId;
            refreshDetail().then(renderPaper);
        }
        const open = e.target.closest('[data-paper-result]');
        if (open) {
            openResultOnChart(open.dataset.paperResult,
                (_detail && _detail.timeframe) || '',
                (_detail && _detail.board_id) || '');
        }
    });
    pane.addEventListener('change', (e) => {
        if (e.target && e.target.id === 'paper-script') {
            renderParamFields(e.target.value);
        }
    });
    window.addEventListener('ak:paper-event', () => {
        if (paneVisible() && !_creating) refresh().then(renderPaper);
    });
    window.addEventListener('ak:paper-create', (e) => {
        _prefill = e.detail || {};
        _creating = true;
        _tab = 'overview';
        loadStrategies().then(renderPaper);
    });
    window.addEventListener('ak:open-paper', (e) => {
        const sid = e.detail && e.detail.session_id;
        if (!sid) return;
        _active = sid;
        _creating = false;
        _tab = 'overview';
        refresh().then(renderPaper);
    });
    _timer = setInterval(() => {
        if (paneVisible() && _active && !_creating) refreshDetail().then(renderPaper);
    }, 5000);
}

export function renderPaper() {
    const pane = currentPane();
    if (!pane) return;
    if (!state.currentBoard) {
        pane.textContent = '';
        pane.appendChild(el('div', 'wb-empty', t('paper.no_board')));
        return;
    }
    if (!_loaded) {
        _loaded = true;
        refresh().then(renderPaper);
    }
    pane.textContent = '';
    const wrap = el('div', 'paper-wrap');
    wrap.appendChild(renderSide());
    wrap.appendChild(renderDetail());
    pane.appendChild(wrap);
}

function renderSide() {
    const side = el('div', 'paper-side');
    const head = el('div', 'paper-head');
    head.appendChild(el('span', 'paper-title', t('paper.title')));
    const add = el('button', 'paper-mini', t('paper.new'));
    add.id = 'paper-new';
    add.type = 'button';
    head.appendChild(add);
    side.appendChild(head);

    if (_creating) side.appendChild(renderCreateForm());

    const list = el('div', 'paper-list');
    if (!_sessions.length) {
        list.appendChild(el('div', 'wb-empty', t('paper.empty')));
    }
    _sessions.forEach(s => {
        const row = el('button', `paper-row${s.session_id === _active ? ' active' : ''}`);
        row.type = 'button';
        row.dataset.sessionId = s.session_id;
        const top = el('div', 'paper-row-top');
        top.appendChild(el('span', 'paper-row-name', `${boardName(s.board_id)} · ${s.timeframe}`));
        top.appendChild(el('span', `paper-badge paper-${s.status}`, statusLabel(s.status)));
        row.appendChild(top);
        const sub = el('div', 'paper-row-sub');
        sub.appendChild(el('span', '', String(s.script || '').split('/').pop()));
        sub.appendChild(el('span', '', fmtMoney(s.equity)));
        row.appendChild(sub);
        list.appendChild(row);
    });
    side.appendChild(list);
    return side;
}

function renderCreateForm() {
    const box = el('div', 'paper-form');
    const head = el('div', 'paper-form-head');
    head.appendChild(el('div', 'paper-form-heading', t('paper.create_title')));
    head.appendChild(el('div', 'paper-form-hint', t('paper.frozen_hint')));
    box.appendChild(head);

    const scroll = el('div', 'paper-form-scroll');
    const board = (state.boards || []).find(b => b.id === state.currentBoard);
    const tfs = (board && board.intervals && board.intervals.length)
        ? board.intervals : [state.currentTimeframe].filter(Boolean);

    const select = (id, options, value) => {
        const sel = el('select', 'paper-select');
        sel.id = id;
        options.forEach(([v, label]) => {
            const o = el('option', '', label);
            o.value = v;
            if (String(v) === String(value)) o.selected = true;
            sel.appendChild(o);
        });
        return sel;
    };
    const num = (id, value, min, step) => {
        const i = el('input', 'paper-input');
        i.id = id;
        i.type = 'number';
        i.value = String(value);
        if (min != null) i.min = String(min);
        if (step != null) i.step = String(step);
        return i;
    };
    const field = (label, node) => {
        const f = el('label', 'paper-field');
        f.appendChild(el('span', 'paper-label', label));
        f.appendChild(node);
        return f;
    };
    const section = (title, items) => {
        const sec = el('div', 'paper-form-section');
        sec.appendChild(el('div', 'paper-section-title', title));
        const grid = el('div', 'paper-form-grid');
        items.forEach(([label, node]) => grid.appendChild(field(label, node)));
        sec.appendChild(grid);
        scroll.appendChild(sec);
        return grid;
    };

    const pre = _prefill || {};
    const scriptOptions = (_strategies || []).length
        ? (_strategies || []).map(st => [st.id, st.display || st.id])
        : [['', t('paper.no_script')]];
    const preScript = pre.script && scriptOptions.some(([id]) => id === pre.script)
        ? pre.script : (scriptOptions[0] ? scriptOptions[0][0] : '');
    const script = select('paper-script', scriptOptions, preScript);
    const tfValue = pre.timeframe && tfs.includes(pre.timeframe)
        ? pre.timeframe : (state.currentTimeframe || tfs[0] || '');
    section(t('paper.sec.strategy'), [
        [t('paper.script'), script],
        [t('paper.timeframe'), select('paper-timeframe',
            tfs.map(tf => [tf, tf]), tfValue)],
        [t('paper.direction'), select('paper-direction',
            [['long_only', t('paper.dir.long')], ['short_only', t('paper.dir.short')],
                ['both', t('paper.dir.both')]], pre.direction || 'long_only')],
    ]);
    section(t('paper.sec.capital'), [
        [t('paper.initial_cash'), num('paper-cash', 10000, 1, 100)],
        [t('paper.fee'), num('paper-fee', 5, 0, 0.1)],
        [t('paper.slippage'), num('paper-slip', 5, 0, 0.1)],
    ]);
    const autoWin = el('input', 'paper-check');
    autoWin.type = 'checkbox';
    autoWin.id = 'paper-window-auto';
    autoWin.checked = true;
    const winInput = num('paper-window', 0, 100, 100);
    winInput.disabled = true;
    const winWrap = el('div', 'paper-window-row');
    const winToggle = el('label', 'paper-check-label');
    winToggle.append(autoWin, el('span', '', t('paper.window_auto')));
    winWrap.append(winToggle, winInput);
    const syncWindowInput = () => {
        winInput.disabled = autoWin.checked;
        winInput.style.display = autoWin.checked ? 'none' : '';
        if (autoWin.checked) winInput.value = '0';
        else if (Number(winInput.value) < 100) winInput.value = '500';
    };
    autoWin.addEventListener('change', syncWindowInput);
    syncWindowInput();
    section(t('paper.sec.risk'), [
        [t('paper.stop_loss'), num('paper-sl', 0, 0, 0.1)],
        [t('paper.take_profit'), num('paper-tp', 0, 0, 0.1)],
        [t('paper.window_bars'), winWrap],
    ]);
    const psec = el('div', 'paper-form-section');
    psec.appendChild(el('div', 'paper-section-title', t('paper.sec.params')));
    const pbox = el('div', 'paper-form-grid');
    pbox.id = 'paper-params';
    psec.appendChild(pbox);
    scroll.appendChild(psec);
    box.appendChild(scroll);
    renderParamFields(script.value, pbox, pre.params || null);

    const foot = el('div', 'paper-form-actions');
    const ok = el('button', 'btn-primary paper-btn', t('paper.create'));
    ok.id = 'paper-create';
    ok.type = 'button';
    const cancel = el('button', 'btn-ghost paper-btn', t('paper.cancel'));
    cancel.id = 'paper-cancel';
    cancel.type = 'button';
    foot.append(ok, cancel);
    box.appendChild(foot);
    return box;
}

function renderParamFields(strategyId, target = null, overrides = null) {
    const box = target || document.getElementById('paper-params');
    if (!box) return;
    box.textContent = '';
    const st = (_strategies || []).find(s => s.id === strategyId);
    const params = (st && st.params) || {};
    const meta = (st && st.param_meta) || {};
    const pick = (key) => (overrides && Object.prototype.hasOwnProperty.call(overrides, key))
        ? overrides[key] : params[key];
    const keys = Object.keys(params);
    if (!keys.length) {
        box.appendChild(el('div', 'paper-muted', t('paper.no_params')));
        return;
    }
    keys.forEach(key => {
        const m = meta[key] || {};
        const type = m.type || typeof params[key];
        const f = el('label', 'paper-field');
        f.appendChild(el('span', 'paper-label', m.label || key));
        let input;
        const val = pick(key);
        if (Array.isArray(m.options)) {
            input = el('select', 'paper-select');
            m.options.forEach(v => {
                const o = el('option', '', String(v));
                o.value = String(v);
                if (String(v) === String(val)) o.selected = true;
                input.appendChild(o);
            });
        } else if (type === 'bool') {
            input = el('select', 'paper-select');
            [[true, t('paper.true')], [false, t('paper.false')]].forEach(([v, label]) => {
                const o = el('option', '', label);
                o.value = v ? 'true' : 'false';
                if (Boolean(val) === v) o.selected = true;
                input.appendChild(o);
            });
        } else {
            input = el('input', 'paper-input');
            input.type = (type === 'int' || type === 'float') ? 'number' : 'text';
            input.value = String(val);
            if (m.min != null) input.min = String(m.min);
            if (m.max != null) input.max = String(m.max);
            if (type === 'int') input.step = '1';
            else if (type === 'float') input.step = String(m.step || 'any');
        }
        input.dataset.paperParam = key;
        input.dataset.paramType = type;
        f.appendChild(input);
        box.appendChild(f);
    });
}

function renderDetail() {
    const main = el('div', 'paper-main');
    const s = _detail;
    if (!s) {
        main.appendChild(el('div', 'wb-empty', t('paper.pick')));
        return main;
    }
    const head = el('div', 'paper-detail-head');
    const title = el('div', 'paper-detail-title');
    title.appendChild(el('span', '', `${boardName(s.board_id)} · ${s.timeframe}`));
    title.appendChild(el('span', `paper-badge paper-${s.status}`, statusLabel(s.status)));
    const w = s.window || {};
    head.appendChild(title);
    const actions = el('div', 'paper-actions');
    actions.appendChild(actionBtn('reconcile', s.session_id, t('paper.reconcile')));
    if (s.status === 'created') actions.appendChild(actionBtn('start', s.session_id, t('paper.start')));
    if (s.status === 'running') {
        actions.appendChild(actionBtn('pause', s.session_id, t('paper.pause')));
        actions.appendChild(actionBtn('stop', s.session_id, t('paper.stop'), 'danger'));
    }
    if (['paused', 'paused_gap', 'error'].includes(s.status)) {
        actions.appendChild(actionBtn('resume', s.session_id, t('paper.resume')));
        actions.appendChild(actionBtn('stop', s.session_id, t('paper.stop'), 'danger'));
    }
    if (s.status === 'stopped' && s.result_id) {
        const b = el('button', 'paper-mini', t('paper.open_result'));
        b.type = 'button';
        b.dataset.paperResult = s.result_id;
        actions.appendChild(b);
    }
    if (s.status !== 'running') {
        actions.appendChild(actionBtn('delete', s.session_id, t('paper.delete'), 'danger'));
    }
    head.appendChild(actions);
    main.appendChild(head);

    if (s.last_error) {
        main.appendChild(el('div', 'paper-error', s.last_error));
    }
    main.appendChild(renderTabs(s));

    const body = el('div', 'paper-tab-body');
    const tab = ['overview', 'trades', 'fills', 'events', 'reconcile'].includes(_tab)
        ? _tab : 'overview';
    if (tab === 'overview') {
        body.appendChild(renderOverview(s));
    } else if (tab === 'trades') {
        body.appendChild(renderTrades(s));
    } else if (tab === 'fills') {
        body.appendChild(renderFills(s));
    } else if (tab === 'events') {
        body.appendChild(renderWarnings(s));
        body.appendChild(renderEvents(s));
    } else {
        body.appendChild(renderReconcile(s));
    }
    main.appendChild(body);
    return main;
}

function renderTabs(s) {
    const warnings = _warningEvents(s).length;
    const rep = (_reconcileSid === s.session_id && _reconcile) || s.last_reconcile;
    const tabs = [
        ['overview', t('paper.tab.overview')],
        ['trades', `${t('paper.tab.trades')} ${s.trade_count ?? 0}`],
        ['fills', `${t('paper.tab.fills')} ${s.fill_count ?? 0}`],
        ['events', `${t('paper.tab.events')} ${warnings || ''}`.trim()],
        ['reconcile', rep ? `${t('paper.tab.reconcile')} · ${_verdictLabel(rep.verdict)}` : t('paper.tab.reconcile')],
    ];
    const box = el('div', 'paper-tabs');
    tabs.forEach(([id, label]) => {
        const b = el('button', `paper-tab${_tab === id ? ' on' : ''}`, label);
        b.type = 'button';
        b.dataset.paperTab = id;
        box.appendChild(b);
    });
    return box;
}

function renderOverview(s) {
    const box = el('div', 'paper-overview');
    box.appendChild(renderPosition(s));
    box.appendChild(renderAccount(s));
    box.appendChild(renderWindow(s));
    box.appendChild(renderEquity(s));
    box.appendChild(renderDecision(s));
    return box;
}

function renderWindow(s) {
    const w = s.window || {};
    const line = el('div', 'paper-window-line');
    const mode = w.mode === 'auto' ? t('paper.window_mode.auto') : t('paper.window_mode.manual');
    line.appendChild(el('span', 'paper-k', t('paper.window')));
    line.appendChild(el('span', '', `${mode} · ${t('paper.window_requested')} ${w.resolved ?? '—'}`));
    line.appendChild(el('span', '', `${t('paper.window_actual')} ${w.actual ?? '—'}`));
    line.appendChild(el('span', '', `WARMUP ${w.warmup ?? 0}`));
    if (w.adjusted) line.appendChild(el('span', 'paper-warn-text', t('paper.window_adjusted')));
    return line;
}

function _chartTime(ms, span) {
    const d = new Date(Number(ms));
    if (!Number.isFinite(d.getTime())) return '—';
    const p = (n) => String(n).padStart(2, '0');
    if (span <= 3 * 86_400_000) {
        return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    }
    if (span <= 365 * 86_400_000) {
        return `${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    }
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}`;
}

function renderEquity(s) {
    const box = el('div', 'paper-section paper-equity-box');
    const head = el('div', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.equity_curve')));
    const rawPts = (_equity && _equity.points) || [];
    const vals = rawPts.map(p => Number(p[1])).filter(Number.isFinite);
    const init = Number(s.initial_cash) || vals[0] || 0;
    // 账本从第一根已处理 bar 的收盘权益开始；图上前补一个初始资金锚点，
    // 否则第一笔成交的手续费/滑点会让曲线看起来“一开始就不是 10000”。
    let pts = rawPts;
    if (rawPts.length && Math.abs(Number(rawPts[0][1]) - init) > 1e-9) {
        const step = rawPts.length > 1
            ? Math.max(1, Number(rawPts[1][0]) - Number(rawPts[0][0]))
            : 15 * 60_000;
        pts = [[Number(rawPts[0][0]) - step, init], ...rawPts];
    }
    if (pts.length === 1) {
        // 刚启动、还没有 B 收盘权益：用一段同值横线表示“尚未产生交易”
        const step = 15 * 60_000;
        pts = [pts[0], [Number(pts[0][0]) + step, Number(pts[0][1])]];
    }
    // 第一笔成交发生在 B 开盘；补一个 B 开盘前的同值点，
    // 让“启动 → 首笔成交”呈现为一段平的初始资金，而不是斜线。
    const firstDiff = pts.findIndex(p => Math.abs(Number(p[1]) - init) > 1e-9);
    if (firstDiff > 0 && Math.abs(Number(pts[firstDiff - 1][1]) - init) <= 1e-9) {
        pts = [...pts.slice(0, firstDiff),
            [Number(pts[firstDiff][0]), init],
            ...pts.slice(firstDiff)];
    }
    head.appendChild(el('span', 'paper-muted', rawPts.length ? `${rawPts.length} ${t(rawPts.length === 1 ? 'paper.point' : 'paper.points')}` : ''));
    box.appendChild(head);
    if (!pts.length) {
        box.appendChild(el('div', 'paper-muted', t('paper.no_equity')));
        return box;
    }
    let lo = init, hi = init;
    vals.forEach(v => { if (v < lo) lo = v; if (v > hi) hi = v; });
    if (Math.abs(hi - lo) < 1e-9) {
        const padVal = Math.max(Math.abs(hi) * 0.001, 1);
        lo -= padVal;
        hi += padVal;
    }
    const span = hi - lo || 1;

    const W = 620, H = 150, pad = 6;
    const t0 = Number(pts[0][0]);
    const t1 = Number(pts[pts.length - 1][0]);
    const x = (i) => {
        if (t1 <= t0) return pad;
        return pad + (Number(pts[i][0]) - t0) / (t1 - t0) * (W - pad * 2);
    };
    const y = (v) => H - pad - ((Number(v) - lo) / span) * (H - pad * 2);
    const NS = 'http://www.w3.org/2000/svg';

    const wrap = el('div', 'paper-chart-wrap');
    const yAxis = el('div', 'paper-chart-y');
    const main = el('div', 'paper-chart-main');
    const plot = el('div', 'paper-chart-plot');
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('class', 'paper-chart');
    svg.setAttribute('preserveAspectRatio', 'none');

    // 横向网格 + 权益刻度：把离初始资金最近的一档吸附到初始值，
    // 这样 10,000 会作为一个真实刻度显示，而不是只显示 9,999.01。
    const gridVals = [hi, lo + span * 2 / 3, lo + span / 3, lo];
    let snapIdx = 0;
    gridVals.forEach((v, i) => {
        if (Math.abs(v - init) < Math.abs(gridVals[snapIdx] - init)) snapIdx = i;
    });
    gridVals[snapIdx] = init;
    gridVals.forEach(v => {
        const line = document.createElementNS(NS, 'line');
        line.setAttribute('x1', pad); line.setAttribute('x2', W - pad);
        line.setAttribute('y1', y(v)); line.setAttribute('y2', y(v));
        line.setAttribute('class', 'paper-chart-grid');
        svg.appendChild(line);
        yAxis.appendChild(el('span', '', fmtMoney(v)));
    });

    // 纵向网格：对应下方 4 个时间标签
    [0, 1 / 3, 2 / 3, 1].forEach(r => {
        const gx = pad + r * (W - pad * 2);
        const line = document.createElementNS(NS, 'line');
        line.setAttribute('x1', gx); line.setAttribute('x2', gx);
        line.setAttribute('y1', pad); line.setAttribute('y2', H - pad);
        line.setAttribute('class', 'paper-chart-grid');
        svg.appendChild(line);
    });

    const axis = document.createElementNS(NS, 'path');
    axis.setAttribute('d', `M${pad},${pad} L${pad},${H - pad} L${W - pad},${H - pad}`);
    axis.setAttribute('class', 'paper-chart-axis');
    svg.appendChild(axis);

    const base = document.createElementNS(NS, 'line');
    base.setAttribute('x1', pad); base.setAttribute('x2', W - pad);
    base.setAttribute('y1', y(init)); base.setAttribute('y2', y(init));
    base.setAttribute('class', 'paper-chart-base');
    svg.appendChild(base);

    const poly = document.createElementNS(NS, 'polyline');
    poly.setAttribute('points', pts.map((p, i) => `${x(i)},${y(p[1])}`).join(' '));
    poly.setAttribute('class', `paper-chart-line ${Number(vals[vals.length - 1]) >= init ? 'up' : 'down'}`);
    svg.appendChild(poly);
    plot.appendChild(svg);
    main.appendChild(plot);

    // 时间轴
    const xAxis = el('div', 'paper-chart-x');
    const tspan = Math.max(0, t1 - t0);
    [0, 1 / 3, 2 / 3, 1].forEach(r => {
        xAxis.appendChild(el('span', '', _chartTime(t0 + r * tspan, tspan)));
    });
    main.appendChild(xAxis);
    wrap.append(yAxis, main);
    box.appendChild(wrap);

    const legend = el('div', 'paper-chart-legend');
    legend.appendChild(el('span', '', `${t('paper.low')} ${fmtMoney(lo)}`));
    legend.appendChild(el('span', '', `${t('paper.high')} ${fmtMoney(hi)}`));
    legend.appendChild(el('span', '', `${t('paper.last')} ${fmtMoney(vals[vals.length - 1])}`));
    legend.appendChild(el('span', '', `${t('paper.initial_cash')} ${fmtMoney(init)}`));
    box.appendChild(legend);
    box.appendChild(el('div', 'paper-chart-note', t('paper.equity_note')));
    return box;
}

function _warningEvents(s) {
    // 0.7.0 的“窗口不足”按请求窗口比较，会把正常短历史误报；0.7.1 已改为
    // 只有连 WARMUP 都不够才告警。历史事件不再展示，避免误导。
    return (s.events || []).filter(e => (e.kind === 'warning' || e.kind === 'error')
        && (e.payload || {}).code !== 'PAPER_WINDOW_SHORT');
}

function renderWarnings(s) {
    const box = el('div', 'paper-section');
    const head = el('div', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.warnings')));
    box.appendChild(head);
    const items = _warningEvents(s);
    if (!items.length && !(s.last_reconcile && (s.last_reconcile.explanations || []).length)) {
        box.appendChild(el('div', 'paper-muted', t('paper.no_warnings')));
        return box;
    }
    items.forEach(ev => {
        const p = ev.payload || {};
        const line = el('div', 'paper-line');
        line.appendChild(el('span', 'paper-event-kind', ev.kind));
        line.appendChild(el('span', 'paper-warn-text', p.code || ''));
        line.appendChild(el('span', '', p.message || ''));
        box.appendChild(line);
    });
    const rep = (_reconcileSid === s.session_id && _reconcile) || s.last_reconcile;
    (rep && rep.explanations || []).forEach(x => {
        const line = el('div', 'paper-line');
        line.appendChild(el('span', 'paper-event-kind', 'reconcile'));
        line.appendChild(el('span', 'paper-warn-text', x.code || ''));
        line.appendChild(el('span', '', x.message || ''));
        box.appendChild(line);
    });
    return box;
}

function _verdictLabel(v) {
    const key = `paper.verdict.${v}`;
    const out = t(key);
    return out === key ? (v || '—') : out;
}

function renderReconcile(s) {
    const box = el('div', 'paper-section paper-reconcile');
    const head = el('div', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.reconcile')));
    const rep = (_reconcileSid === s.session_id && _reconcile) || s.last_reconcile;
    if (rep) {
        head.appendChild(el('span', `paper-badge paper-${rep.verdict === 'match' ? 'running' : rep.verdict === 'explainable' ? 'paused' : 'error'}`,
            _verdictLabel(rep.verdict)));
    }
    box.appendChild(head);
    if (!rep) {
        box.appendChild(el('div', 'paper-muted', t('paper.reconcile_empty')));
        const acts = el('div', 'paper-reconcile-actions');
        acts.append(
            reconcileRunButton(s),
            renderReconcileSave(),
        );
        box.appendChild(acts);
        return box;
    }
    const grid = el('div', 'paper-grid');
    const cells = [
        [t('paper.reconcile_coverage'), `${rep.coverage && rep.coverage.bars || 0} ${t('paper.bars_unit')}`],
        [t('paper.paper_side'), `${rep.paper && rep.paper.fills || 0} ${t('paper.fills_unit')} / ${rep.paper && rep.paper.trades || 0} ${t('paper.closed')}`],
        [t('paper.backtest_side'), `${rep.backtest && rep.backtest.fills || 0} ${t('paper.fills_unit')} / ${rep.backtest && rep.backtest.trades || 0} ${t('paper.closed')}`],
        [t('paper.reconcile_maxdiff'), rep.diff && rep.diff.equity ? fmtMoney(rep.diff.equity.max_abs) : '—'],
    ];
    cells.forEach(([k, v]) => {
        const c = el('div', 'paper-cell');
        c.appendChild(el('span', 'paper-k', k));
        c.appendChild(el('span', 'paper-v', v));
        grid.appendChild(c);
    });
    box.appendChild(grid);
    const dc = rep.diff_counts || {};
    const diffLine = el('div', 'paper-line');
    diffLine.appendChild(el('span', '', `${t('paper.reconcile_diff')}: ` +
        `${t('paper.equity')} ${dc.equity || 0} · ` +
        `${t('paper.fills')} ${(dc.fills_missing || 0) + (dc.fills_extra || 0) + (dc.fills_mismatch || 0)} · ` +
        `${t('paper.trades')} ${(dc.trades_missing || 0) + (dc.trades_extra || 0) + (dc.trades_mismatch || 0)}`));
    box.appendChild(diffLine);
    if (rep.coverage) {
        box.appendChild(el('div', 'paper-muted',
            `${t('paper.reconcile_range')} ${fmtTime(rep.coverage.from)} → ${fmtTime(rep.coverage.to)}`));
    }
    const ex = rep.explanations || [];
    if (ex.length) {
        const list = el('div', 'paper-reconcile-explain');
        list.appendChild(el('div', 'paper-section-title', t('paper.explanations')));
        ex.forEach(x => {
            const line = el('div', 'paper-line');
            line.appendChild(el('span', 'paper-warn-text', x.code || ''));
            line.appendChild(el('span', '', x.message || ''));
            list.appendChild(line);
        });
        box.appendChild(list);
    }
    if (rep.diff) {
        const items = (rep.diff.equity && rep.diff.equity.items) || [];
        if (items.length) {
            box.appendChild(el('div', 'paper-section-title', t('paper.reconcile_equity_diff')));
            items.slice(0, 8).forEach(it => {
                box.appendChild(el('div', 'paper-line paper-warn-text',
                    `${fmtTime(it.time)} paper=${fmtMoney(it.paper)} bt=${fmtMoney(it.backtest)}`));
            });
        }
        const fm = (rep.diff.fills && rep.diff.fills.mismatch) || [];
        if (fm.length) {
            box.appendChild(el('div', 'paper-section-title', t('paper.reconcile_fill_diff')));
            fm.slice(0, 8).forEach(it => {
                box.appendChild(el('div', 'paper-line paper-warn-text',
                    `${fmtTime((it.paper || {}).time)} ${(it.fields || []).join('/')}`));
            });
        }
    }
    const acts = el('div', 'paper-reconcile-actions');
    acts.appendChild(reconcileRunButton(s));
    acts.appendChild(renderReconcileSave());
    if (rep.result_id) {
        const rb = el('button', 'paper-mini', t('paper.reconcile_result'));
        rb.type = 'button';
        rb.dataset.paperResult = rep.result_id;
        acts.appendChild(rb);
    }
    box.appendChild(acts);
    return box;
}

function reconcileRunButton(s) {
    const b = actionBtn('reconcile', s.session_id,
        _reconcileBusy ? t('paper.reconcile_running') : t('paper.reconcile_run'));
    b.disabled = _reconcileBusy;
    return b;
}

function renderReconcileSave() {
    const wrap = el('label', 'paper-check-label paper-reconcile-save');
    const cb = el('input', 'paper-check');
    cb.type = 'checkbox';
    cb.id = 'paper-reconcile-save';
    cb.checked = _saveReconcileResult;
    cb.disabled = _reconcileBusy;
    cb.addEventListener('change', () => { _saveReconcileResult = cb.checked; });
    wrap.append(cb, el('span', '', t('paper.reconcile_save')));
    return wrap;
}

const _sideLabel = (side) => {
    if (side === 'long') return t('paper.long');
    if (side === 'short') return t('paper.short');
    return t('paper.flat');
};
const _pnlClass = (v) => {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? 'up' : Number.isFinite(n) && n < 0 ? 'down' : '';
};
const _fmtSigned = (v) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return `${n > 0 ? '+' : ''}${fmtMoney(n)}`;
};
const _targetLabel = (v) => {
    const n = Number(v);
    if (!Number.isFinite(n) || Math.abs(n) < 1e-9) return t('paper.flat');
    return `${n > 0 ? t('paper.long') : t('paper.short')} ${(Math.abs(n) * 100).toFixed(1)}%`;
};

function renderPosition(s) {
    const card = el('div', 'paper-position-card');
    const head = el('div', 'paper-position-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.current_position')));
    const side = s.position_side || (Number(s.position) > 0 ? 'long' : Number(s.position) < 0 ? 'short' : 'flat');
    head.appendChild(el('span', `paper-badge paper-${s.status}`, _sideLabel(side)));
    card.appendChild(head);
    if (side === 'flat' || Math.abs(Number(s.position) || 0) < 1e-12) {
        card.appendChild(el('div', 'paper-muted', t('paper.no_position')));
        return card;
    }
    const line = el('div', 'paper-position-line');
    const qty = Math.abs(Number(s.position));
    line.appendChild(el('span', 'paper-pos-qty',
        `${_sideLabel(side)} ${fmtNum(qty, 6)}`));
    line.appendChild(el('span', '', `${t('paper.avg_price')} ${fmtNum(s.avg_price, 4)}`));
    line.appendChild(el('span', '', `${t('paper.last_price')} ${fmtNum(s.last_price, 4)} · ${s.timeframe} ${t('paper.bar')} ${fmtTime(s.last_price_ts)}`));
    line.appendChild(el('span', '', `${t('paper.notional')} ${fmtMoney(s.position_notional)}`));
    card.appendChild(line);
    const pnl = el('div', `paper-position-pnl ${_pnlClass(s.unrealized_pnl)}`);
    pnl.textContent = `${t('paper.unrealized')} ${_fmtSigned(s.unrealized_pnl)} (${fmtPct(s.unrealized_pct)})`;
    card.appendChild(pnl);
    card.appendChild(el('div', 'paper-price-note', t('paper.price_note')));
    return card;
}

function renderAccount(s) {
    const grid = el('div', 'paper-grid');
    const cells = [
        { k: t('paper.live_equity'), v: fmtMoney(s.live_equity ?? s.equity) },
        { k: t('paper.settled_equity'), v: fmtMoney(s.equity) },
        { k: t('paper.initial_cash'), v: fmtMoney(s.initial_cash) },
        { k: t('paper.realized'), v: _fmtSigned(s.realized_pnl), p: s.realized_pnl },
        { k: t('paper.unrealized'), v: _fmtSigned(s.unrealized_pnl), p: s.unrealized_pnl },
        { k: t('paper.total_return'), v: fmtPct(s.total_return), p: s.total_return },
        { k: t('paper.fees'), v: fmtMoney(s.total_fees) },
        { k: t('paper.bars'), v: String(s.bars_processed ?? 0) },
    ];
    cells.forEach(({ k, v, p }) => {
        const c = el('div', 'paper-cell');
        c.appendChild(el('span', 'paper-k', k));
        const val = el('span', `paper-v ${p == null ? '' : _pnlClass(p)}`);
        val.textContent = v;
        c.appendChild(val);
        grid.appendChild(c);
    });
    return grid;
}

function renderDecision(s) {
    const box = el('div', 'paper-section paper-decision');
    const head = el('div', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.last_decision')));
    box.appendChild(head);
    const d = s.last_decision;
    if (!d) {
        box.appendChild(el('div', 'paper-muted', t('paper.no_decision')));
        return box;
    }
    const line = el('div', 'paper-line');
    line.appendChild(el('span', '', `${t('paper.bar')} ${fmtTime(d.bar_ts)}`));
    line.appendChild(el('span', '', `${t('paper.target_position')} ${_targetLabel(d.target)}`));
    line.appendChild(el('span', '', `${t('paper.reason')} ${d.reason || '—'}`));
    line.appendChild(el('span', 'paper-muted', t('paper.next_open_hint')));
    box.appendChild(line);
    return box;
}

function _td(text, cls = '') {
    const td = el('td', cls);
    td.textContent = text == null ? '—' : String(text);
    return td;
}

function _table(headers, rows) {
    const wrap = el('div', 'paper-table-wrap');
    const table = el('table', 'paper-table');
    const thead = el('thead');
    const trh = el('tr');
    headers.forEach(h => trh.appendChild(el('th', '', h)));
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el('tbody');
    rows.forEach(cells => {
        const tr = el('tr');
        cells.forEach(([text, cls]) => tr.appendChild(_td(text, cls)));
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
}

function renderTrades(s) {
    const box = el('div', 'paper-section');
    const head = el('div', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.trade_process')));
    head.appendChild(el('span', 'paper-muted', `${s.trade_count ?? 0} ${t('paper.closed')}`));
    box.appendChild(head);
    const rows = [];
    (s.trades || []).forEach(tr => {
        rows.push([
            [_sideLabel(tr.side)],
            [fmtTime(tr.entry_time)],
            [fmtTime(tr.exit_time)],
            [fmtNum(tr.size, 6)],
            [fmtNum(tr.entry_price, 4)],
            [fmtNum(tr.exit_price, 4)],
            ['—'],
            [`${_fmtSigned(tr.pnl)} (${fmtPct(tr.pnl_pct)})`, _pnlClass(tr.pnl)],
            [tr.holding_bars == null ? '—' : `${tr.holding_bars}`],
            [`${tr.entry_reason || '—'} → ${tr.exit_reason || '—'}`],
        ]);
    });
    if (s.open_trade) {
        const t0 = s.open_trade;
        rows.push([
            [_sideLabel(t0.side), 'paper-open'],
            [fmtTime(t0.entry_time), 'paper-open'],
            [t('paper.open_position'), 'paper-open'],
            [fmtNum(t0.size, 6), 'paper-open'],
            [fmtNum(t0.entry_price, 4), 'paper-open'],
            ['—', 'paper-open'],
            [fmtNum(s.last_price, 4), 'paper-open'],
            [`${_fmtSigned(t0.pnl)} (${fmtPct(t0.pnl_pct)})`, `${_pnlClass(t0.pnl)} paper-open`],
            [t0.holding_bars == null ? '—' : `${t0.holding_bars}`, 'paper-open'],
            [t0.entry_reason || '—', 'paper-open'],
        ]);
    }
    if (!rows.length) {
        box.appendChild(el('div', 'paper-muted', t('paper.no_trades')));
        return box;
    }
    box.appendChild(_table([
        t('paper.direction'), t('paper.entry'), t('paper.exit'), t('paper.qty'),
        t('paper.entry_price'), t('paper.exit_price'), t('paper.last_price'),
        t('paper.pnl'), t('paper.holding'), t('paper.reason'),
    ], rows));
    return box;
}

function renderFills(s) {
    const box = el('div', 'paper-section');
    const head = el('div', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.fills')));
    head.appendChild(el('span', 'paper-muted', `${s.fill_count ?? 0} ${t('paper.fills_unit')}`));
    box.appendChild(head);
    const rows = (s.fills || []).slice(-8).reverse().map(f => [
        [fmtTime(f.time)],
        [f.action === 'buy' ? t('paper.buy') : t('paper.sell')],
        [fmtNum(f.price, 4)],
        [fmtNum(Math.abs(f.signed_qty), 6)],
        [fmtMoney(f.notional)],
        [fmtMoney(f.fee)],
        [f.reason || '—'],
    ]);
    if (!rows.length) {
        box.appendChild(el('div', 'paper-muted', t('paper.no_trades')));
        return box;
    }
    box.appendChild(_table([
        t('paper.time'), t('paper.action'), t('paper.price'), t('paper.qty'),
        t('paper.notional'), t('paper.fees'), t('paper.reason'),
    ], rows));
    return box;
}

function renderEvents(s) {
    const details = el('details', 'paper-section paper-events');
    const head = el('summary', 'paper-section-head');
    head.appendChild(el('span', 'paper-section-title', t('paper.recent')));
    head.appendChild(el('span', 'paper-muted', t('paper.events_hint')));
    details.appendChild(head);
    const items = s.events || [];
    if (!items.length) {
        details.appendChild(el('div', 'paper-muted', t('paper.no_events')));
        return details;
    }
    items.slice(0, 12).forEach(ev => {
        const line = el('div', 'paper-line paper-event');
        line.appendChild(el('span', 'paper-event-kind', ev.kind));
        line.appendChild(el('span', '', ev.kind === 'fill'
            ? `${ev.payload.action === 'buy' ? t('paper.buy') : t('paper.sell')} ${fmtNum(ev.payload.price, 4)} @ ${fmtTime(ev.bar_ts)}`
            : ev.kind === 'equity'
                ? `${t('paper.equity')} ${fmtMoney(ev.payload.equity)}`
                : ev.kind === 'decision'
                    ? `${t('paper.target_position')} ${_targetLabel(ev.payload.target)}`
                    : (ev.payload.message || ev.payload.code || '')));
        details.appendChild(line);
    });
    return details;
}

function actionBtn(action, id, label, kind = '') {
    const b = el('button', `paper-mini${kind ? ` paper-${kind}` : ''}`, label);
    b.type = 'button';
    b.dataset.paperAction = action;
    b.dataset.sessionId = id;
    return b;
}

async function loadStrategies() {
    if (_strategies) return _strategies;
    try {
        const j = await req('/api/strategies');
        _strategies = j.strategies || [];
    } catch (e) {
        _strategies = [];
        toast(e.message);
    }
    return _strategies;
}

async function refresh() {
    try {
        const j = await req('/api/paper/sessions');
        _sessions = j.sessions || [];
        if (!_active && _sessions.length) _active = _sessions[0].session_id;
        if (_active && !_sessions.some(s => s.session_id === _active)) {
            _active = _sessions.length ? _sessions[0].session_id : null;
        }
        if (_active) await refreshDetail();
        if (!_active) _detail = null;
    } catch (e) {
        _sessions = [];
        _detail = null;
    }
}

async function refreshDetail() {
    if (!_active) { _detail = null; _equity = null; return; }
    try {
        const sid = encodeURIComponent(_active);
        const [detail, equity] = await Promise.all([
            req(`/api/paper/sessions/${sid}?include_events=true`),
            req(`/api/paper/sessions/${sid}/equity`).catch(() => null),
        ]);
        _detail = detail;
        _equity = equity;
        if (_reconcileSid && _reconcileSid !== _active) {
            _reconcile = null;
            _reconcileSid = null;
        }
    } catch (e) {
        _detail = null;
        _equity = null;
    }
}

async function action(kind, sessionId) {
    if (!kind || !sessionId) return;
    if (kind === 'reconcile') {
        await runReconcile(sessionId);
        return;
    }
    if (kind === 'delete') {
        const yes = await openDialog({
            title: t('paper.delete'),
            message: t('paper.delete_confirm'),
            confirmText: t('paper.delete'),
            danger: true,
        });
        if (!yes) return;
    }
    try {
        const base = `/api/paper/sessions/${encodeURIComponent(sessionId)}`;
        const url = kind === 'delete' ? base : `${base}/${kind}`;
        await req(url, {
            method: kind === 'delete' ? 'DELETE' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: kind === 'delete' ? undefined : '{}',
        });
        if (kind === 'delete') {
            _active = null;
            _detail = null;
        }
        await refresh();
    } catch (e) {
        toast(e.message);
        await refresh();
    }
    renderPaper();
}

async function openResultOnChart(resultId, timeframe, boardId) {
    if (!resultId) return;
    try {
        if (boardId && boardId !== state.currentBoard) {
            await fetch(`/api/board/${encodeURIComponent(boardId)}`, { cache: 'no-store' });
            await new Promise(resolve => setTimeout(resolve, 700));
        }
        if (timeframe && timeframe !== state.currentTimeframe) {
            await fetch(`/api/board/${encodeURIComponent(boardId || state.currentBoard)}` +
                `/timeframe/${encodeURIComponent(timeframe)}`, { cache: 'no-store' });
            await new Promise(resolve => setTimeout(resolve, 900));
        }
    } catch (e) { /* 切换失败时仍尝试按当前周期打开 */ }
    window.dispatchEvent(new CustomEvent('ak:open-result', {
        detail: { id: resultId },
    }));
}

async function runReconcile(sessionId) {
    if (_reconcileBusy) return;
    _reconcileBusy = true;
    toast(t('paper.reconcile_running'));
    renderPaper();
    try {
        const out = await req(`/api/paper/sessions/${encodeURIComponent(sessionId)}/reconcile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ save_result: !!_saveReconcileResult }),
        });
        _reconcile = out;
        _reconcileSid = sessionId;
        _tab = 'reconcile';
        if (out.result_id) {
            toast(t('paper.reconcile_saved'));
            await openResultOnChart(out.result_id,
                (_detail && _detail.timeframe) || '',
                (_detail && _detail.board_id) || '');
        } else {
            toast(out.match ? t('paper.reconcile_ok') : t('paper.reconcile_bad'));
        }
        await refreshDetail();
    } catch (e) {
        toast(e.message);
    } finally {
        _reconcileBusy = false;
        await refreshDetail();
        renderPaper();
    }
}

async function createSession() {
    const script = document.getElementById('paper-script');
    const dir = document.getElementById('paper-direction');
    if (!state.currentBoard || !state.currentTimeframe) {
        toast(t('paper.no_board'));
        return;
    }
    if (!script || !script.value) {
        toast(t('paper.no_script'));
        return;
    }
    const val = (id) => {
        const el = document.getElementById(id);
        return el ? String(el.value || '').trim() : '';
    };
    const num = (id, fallback) => {
        const n = Number(val(id));
        return Number.isFinite(n) ? n : fallback;
    };
    const cash = num('paper-cash', 10000);
    const fee = num('paper-fee', 5);
    const slip = num('paper-slip', 5);
    const autoWin = document.getElementById('paper-window-auto');
    const autoWindow = !autoWin || autoWin.checked;
    const windowBars = autoWindow ? 0 : num('paper-window', 0);
    const sl = num('paper-sl', 0);
    const tp = num('paper-tp', 0);
    if (!(cash > 0) || fee < 0 || slip < 0 || (!autoWindow && windowBars < 100)) {
        toast(t('paper.bad_numbers'));
        return;
    }
    const body = {
        board_id: state.currentBoard,
        timeframe: val('paper-timeframe') || state.currentTimeframe,
        script: script.value,
        direction: dir ? dir.value : 'long_only',
        initial_cash: cash,
        fee_bps: fee,
        slippage_bps: slip,
        window_bars: autoWindow ? 0 : Math.round(windowBars),
    };
    const params = {};
    document.querySelectorAll('#paper-params [data-paper-param]').forEach(input => {
        const key = input.dataset.paperParam;
        const type = input.dataset.paramType;
        if (type === 'bool') params[key] = input.value === 'true';
        else if (type === 'int') params[key] = parseInt(input.value, 10);
        else if (type === 'float' || type === 'number') params[key] = Number(input.value);
        else params[key] = input.value;
    });
    if (Object.keys(params).length) body.params = params;
    if (sl > 0 || tp > 0) {
        body.protection = {};
        if (sl > 0) body.protection.stop_loss_pct = sl / 100;
        if (tp > 0) body.protection.take_profit_pct = tp / 100;
    }
    try {
        const out = await req('/api/paper/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        _creating = false;
        _prefill = null;
        _tab = 'overview';
        _active = out.session_id || null;
        await refresh();
    } catch (e) {
        toast(e.message);
    }
    renderPaper();
}
