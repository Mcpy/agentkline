// ============================================================
// 模拟盘（v0.7.0）：最小工作坞面板
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
        const msg = (detail && (detail.error || detail.message)) || (body && body.error)
            || `HTTP ${r.status}`;
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
        if (e.target.closest('#paper-new')) {
            _creating = true;
            loadStrategies().then(renderPaper);
            return;
        }
        if (e.target.closest('#paper-cancel')) {
            _creating = false;
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
            window.dispatchEvent(new CustomEvent('ak:open-result', { detail: { id: open.dataset.paperResult } }));
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

    const script = select('paper-script',
        (_strategies || []).length
            ? (_strategies || []).map(st => [st.id, st.display || st.id])
            : [['', t('paper.no_script')]],
        (_strategies || []).length ? _strategies[0].id : '');
    section(t('paper.sec.strategy'), [
        [t('paper.script'), script],
        [t('paper.timeframe'), select('paper-timeframe',
            tfs.map(tf => [tf, tf]), state.currentTimeframe || tfs[0] || '')],
        [t('paper.direction'), select('paper-direction',
            [['long_only', t('paper.dir.long')], ['short_only', t('paper.dir.short')],
                ['both', t('paper.dir.both')]], 'long_only')],
    ]);
    section(t('paper.sec.capital'), [
        [t('paper.initial_cash'), num('paper-cash', 10000, 1, 100)],
        [t('paper.fee'), num('paper-fee', 5, 0, 0.1)],
        [t('paper.slippage'), num('paper-slip', 5, 0, 0.1)],
    ]);
    section(t('paper.sec.risk'), [
        [t('paper.stop_loss'), num('paper-sl', 0, 0, 0.1)],
        [t('paper.take_profit'), num('paper-tp', 0, 0, 0.1)],
        [t('paper.window_bars'), num('paper-window', 5000, 100, 100)],
    ]);
    const psec = el('div', 'paper-form-section');
    psec.appendChild(el('div', 'paper-section-title', t('paper.sec.params')));
    const pbox = el('div', 'paper-form-grid');
    pbox.id = 'paper-params';
    psec.appendChild(pbox);
    scroll.appendChild(psec);
    box.appendChild(scroll);
    renderParamFields(script.value, pbox);

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

function renderParamFields(strategyId, target = null) {
    const box = target || document.getElementById('paper-params');
    if (!box) return;
    box.textContent = '';
    const st = (_strategies || []).find(s => s.id === strategyId);
    const params = (st && st.params) || {};
    const meta = (st && st.param_meta) || {};
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
        if (Array.isArray(m.options)) {
            input = el('select', 'paper-select');
            m.options.forEach(v => {
                const o = el('option', '', String(v));
                o.value = String(v);
                if (String(v) === String(params[key])) o.selected = true;
                input.appendChild(o);
            });
        } else if (type === 'bool') {
            input = el('select', 'paper-select');
            [[true, t('paper.true')], [false, t('paper.false')]].forEach(([v, label]) => {
                const o = el('option', '', label);
                o.value = v ? 'true' : 'false';
                if (Boolean(params[key]) === v) o.selected = true;
                input.appendChild(o);
            });
        } else {
            input = el('input', 'paper-input');
            input.type = (type === 'int' || type === 'float') ? 'number' : 'text';
            input.value = String(params[key]);
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
    head.appendChild(title);
    const actions = el('div', 'paper-actions');
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

    main.appendChild(renderPosition(s));
    main.appendChild(renderAccount(s));
    main.appendChild(renderDecision(s));
    main.appendChild(renderTrades(s));
    main.appendChild(renderFills(s));
    main.appendChild(renderEvents(s));
    return main;
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
    line.appendChild(el('span', '', `${t('paper.last_price_15m')} ${fmtNum(s.last_price, 4)} · ${t('paper.bar')} ${fmtTime(s.last_price_ts)}`));
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
        t('paper.entry_price'), t('paper.exit_price'), t('paper.last_price_15m'),
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
    if (!_active) { _detail = null; return; }
    try {
        _detail = await req(`/api/paper/sessions/${encodeURIComponent(_active)}?include_events=true`);
    } catch (e) {
        _detail = null;
    }
}

async function action(kind, sessionId) {
    if (!kind || !sessionId) return;
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
    const windowBars = num('paper-window', 5000);
    const sl = num('paper-sl', 0);
    const tp = num('paper-tp', 0);
    if (!(cash > 0) || fee < 0 || slip < 0 || windowBars < 100) {
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
        window_bars: Math.round(windowBars),
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
        _active = out.session_id || null;
        await refresh();
    } catch (e) {
        toast(e.message);
    }
    renderPaper();
}
