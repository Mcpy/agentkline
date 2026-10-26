// ============================================================
// 结果实例（v0.6.0）：结果栏、概览、图层数据、删除/改名
// 结果冻结：重跑=新 id；这里只做选择、取数与呈现，不改内容
// ============================================================
import { state } from './state.js';
import { t } from './i18n.js';
import { formatTimeCN, isIntraday } from './format.js';
import { showContextMenu } from './menu.js';
import { toast } from './search.js';
import { openDialog } from './dialog.js';
import { refreshResultLayer, refreshResultMarksOnly, resultColor, focusTradeRange, tfMs,
         hitTradeMarker, tradeMarkerPoints } from './vela_adapter.js';
import { addActivity } from './activity.js';
import { openWorkbench, renderWorkbench, updateWorkbenchStatus } from './workbench.js';
import { openBacktestDialog } from './backtest.js';

const MAX_VISIBLE = 8;
const TRADE_PAGE = 10;
const SCENES = {};   // `${board}|${tf}` -> {visible:[], active}
const _tradePage = {};   // result_id -> 当前页码
const _tradeSel = {};    // result_id -> 选中的交易 id
let _tradeCtx = null;    // 当前渲染的三栏上下文
let _tradeTab = 'equity';
try {
    const saved = localStorage.getItem('ak_trade_tab');
    _tradeTab = saved === 'pnl' ? 'equity'
        : (['equity', 'cum', 'month'].includes(saved) ? saved : 'equity');
} catch (e) { /* 默认收益曲线 */ }
let _tradesOpen = true;
try { _tradesOpen = localStorage.getItem('ak_trade_open') !== '0'; } catch (e) { /* 默认展开 */ }
let _syncSeq = 0;
let _trustOpen = false;   // 尾部「信任区」details 是否展开（用户手动开合，重渲染保留）

const fmtPct = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `${n >= 0 ? '+' : ''}${(n * 100).toFixed(2)}%` : '—';
};
const fmtPctPlain = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : '—';
};
const fmtNum = (v, d = 2) => {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(d) : '—';
};
const fmtMoney = (v) => {
    const n = Number(v);
    return Number.isFinite(n)
        ? n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
};
const tone = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? (n > 0 ? 'up' : n < 0 ? 'down' : '') : '';
};
const statusLabel = (s) => t(`result.status.${s}`) === `result.status.${s}` ? s : t(`result.status.${s}`);
const sceneKey = () => `${state.currentBoard || ''}|${state.currentTimeframe || ''}`;
const activeSummary = () => (state.results || []).find(r => r.result_id === state.resultActive) || null;

// ---- 信任区：契约字段 -> 人话；未知枚举原样显示，不吞信息 ----
const ASM_LABEL = {
    fill_rule: 'result.asm.fill_rule',
    bar_close_policy: 'result.asm.bar_close_policy',
    intrabar_mode: 'result.asm.intrabar_mode',
    protection_rule: 'result.asm.protection_rule',
    funding_mode: 'result.asm.funding_mode',
    leverage: 'result.asm.leverage',
    lot_policy: 'result.asm.lot_policy',
    corporate_actions: 'result.asm.corporate_actions',
    shorting: 'result.asm.shorting',
    direction: 'result.asm.direction',
    fee_bps: 'result.asm.fee_bps',
    slippage_bps: 'result.asm.slippage_bps',
    calendar: 'result.asm.calendar',
    bars_per_year: 'result.asm.bars_per_year',
    annualization: 'result.asm.annualization',
};
const ASM_VALUE = {
    fill_rule: {
        next_open: 'result.v.next_open', close: 'result.v.close', next_close: 'result.v.next_close',
        open: 'result.v.open', mid: 'result.v.mid', vwap: 'result.v.vwap',
    },
    bar_close_policy: {
        closed_only: 'result.v.closed_only', closed_bars_only: 'result.v.closed_bars_only',
        any_tick: 'result.v.any_tick', open_only: 'result.v.open_only',
    },
    intrabar_mode: {
        conservative: 'result.v.conservative', optimistic: 'result.v.optimistic', none: 'result.v.intrabar_none',
    },
    protection_rule: {
        gap_then_intrabar: 'result.v.gap_then_intrabar',
        gap_open_then_intrabar_trigger: 'result.v.gap_open_then_intrabar_trigger',
        intrabar_only: 'result.v.intrabar_only', close_only: 'result.v.prot_close_only',
    },
    funding_mode: { not_modeled: 'result.v.not_modeled', modeled: 'result.v.modeled' },
    lot_policy: { continuous: 'result.v.continuous', integer: 'result.v.integer', fixed: 'result.v.fixed' },
    corporate_actions: { not_applied: 'result.v.not_applied', applied: 'result.v.applied' },
    shorting: {
        unsupported: 'result.v.unsupported', supported: 'result.v.supported',
        synthetic_no_borrow: 'result.v.synthetic_no_borrow', none: 'result.v.unsupported',
    },
    direction: {
        long_only: 'result.v.long_only', short_only: 'result.v.short_only', both: 'result.v.both',
    },
    calendar: { bar_clock: 'result.v.bar_clock', exchange_calendar: 'result.v.exchange_calendar' },
    annualization: { observed_bar_density: 'result.v.observed_bar_density', fixed_365: 'result.v.fixed_365' },
};
const HASH_LABEL = {
    agentkline_version: 'result.h.version',
    config_hash: 'result.h.config',
    strategy_source_sha256: 'result.h.strategy',
    data_source_sha256: 'result.h.data',
};
const VERDICT_LABEL = { ok: 'result.quality.ok', warn: 'result.quality.warn', bad: 'result.quality.bad' };

const _asmLabel = (k) => (ASM_LABEL[k] ? t(ASM_LABEL[k]) : k);
function _asmValue(k, v) {
    const hit = (ASM_VALUE[k] || {})[String(v)];
    if (hit) return t(hit);
    if (k === 'leverage') return `${v}x`;
    if (k === 'fee_bps' || k === 'slippage_bps') return `${v} bp`;
    return String(v);
}
const _verdictLabel = (v) => (VERDICT_LABEL[v] ? t(VERDICT_LABEL[v]) : (v || '—'));

function _qualityLine(q) {
    const bars = (q.actual && q.actual.bars) || 0;
    const cov = q.coverage == null ? '—' : `${Math.round(q.coverage * 100)}%`;
    return t('result.quality.line', { bars, gaps: q.gaps || 0, dup: q.duplicates || 0, cov });
}

function _trustHint(a) {
    const q = (a.data && a.data.quality) || {};
    const asm = a.execution_assumptions || {};
    const parts = [_verdictLabel(q.verdict)];
    if (asm.fill_rule) parts.push(t('result.trust.fill', { fill: _asmValue('fill_rule', asm.fill_rule) }));
    const fee = a.run && a.run.fee;
    if (fee != null) parts.push(t('result.trust.fee', { fee: `${+(Number(fee) * 100).toFixed(3)}%` }));
    if (Number(asm.leverage) > 1) parts.push(`${asm.leverage}x`);
    return parts.join(' · ');
}

const _shortHash = (v) => (String(v).length > 16 ? `${String(v).slice(0, 12)}...` : String(v));

function _el(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = String(text);
    return el;
}

// ---- 交易详情三栏：列表 / 单笔 / 图 ----
const _SVG_NS = 'http://www.w3.org/2000/svg';

const _tid = (tr) => String(tr.id || `${tr.entry_time}-${tr.exit_time}`);

// 单位优先级：结果声明 units > symbol 的 BASE/QUOTE > 不加后缀
function _unitsOf(a) {
    const u = (a && a.units) || {};
    let quantity = String(u.quantity || '').trim();
    let currency = String(u.currency || '').trim();
    if (!quantity || !currency) {
        const core = String((a && a.data && a.data.symbol) || '').split(':')[0];
        if (core.includes('/')) {
            const [base, quote] = core.split('/');
            if (!quantity && base) quantity = base;
            if (!currency && quote) currency = quote;
        }
    }
    return { base: quantity, quote: currency };
}
const _selId = (ctx) => _tradeSel[ctx.rid] || '';

function _whenText(ms, intraday) {
    const sec = Number(ms);
    return Number.isFinite(sec) ? formatTimeCN(Math.floor(sec / 1000), intraday, state.uiTimezone) : '—';
}

function _tradeTimeCell(ms, px, intraday) {
    const td = _el('td', null, '');
    td.append(
        _el('div', 'res-t-when', _whenText(ms, intraday)),
        _el('div', 'res-t-px', px == null ? '—' : fmtNum(px)),
    );
    return td;
}

function _holdText(bars, tf) {
    const n = Number(bars);
    if (!Number.isFinite(n) || n <= 0) return '—';
    const ms = n * tfMs(tf || state.currentTimeframe);
    if (ms >= 86400e3) return t('result.t.days', { n: Math.round(ms / 86400e3) });
    if (ms >= 3600e3) return t('result.t.hours', { n: Math.round(ms / 3600e3) });
    return t('result.t.minutes', { n: Math.max(1, Math.round(ms / 60e3)) });
}

function _svg(tag, attrs) {
    const el = document.createElementNS(_SVG_NS, tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
}

function _monthKey(ms) {
    const tz = state.uiTimezone && state.uiTimezone !== 'browser' ? state.uiTimezone : undefined;
    try {
        return new Intl.DateTimeFormat('sv-SE', { year: 'numeric', month: '2-digit', timeZone: tz })
            .format(new Date(Number(ms)));
    } catch (e) {
        return String(ms).slice(0, 7);
    }
}

// 选中一笔：只更新详情卡 + 列表/图高亮，不动 K 线；跳转统一走「在图上定位」
function _selectTrade(tr, locate = false) {
    const ctx = _tradeCtx;
    if (!ctx) return;
    _tradeSel[ctx.rid] = _tid(tr);
    state.resultSelTrade = _tid(tr);   // 结果层用它给选中盒子描边、其余降透明度
    document.querySelectorAll('#wb-overview .res-trade-row').forEach(r => {
        r.classList.toggle('sel', r.dataset.tid === _tid(tr));
    });
    _renderTradeDetail();
    _renderTradeChart();
    const _t0 = performance.now();
    refreshResultMarksOnly();
    try { window.__akSelMs = performance.now() - _t0; } catch (e) { /* 计时把手 */ }
    if (locate) _locateTrade(tr);   // 点行即定位（0.6.2 B1）
}

// 唯一的 K 线定位入口：详情卡上的「在图上定位」按钮
//   focusTradeRange 现在会先按需补历史（0.6.1：2020 年的交易也能跳过去），因此是异步；
//   真不可达（补到 2 万根仍不够）才提示 out_of_range。
async function _locateTrade(tr) {
    if (!(await focusTradeRange(tr.entry_time, tr.exit_time))) addActivity('warn', t('result.t.out_of_range'));
}

function _renderTradeDetail() {
    const ctx = _tradeCtx;
    const host = document.querySelector('#wb-overview .res-trade-detail');
    if (!ctx || !host) return;
    host.textContent = '';
    const sel = ctx.trades.find(x => _tid(x) === _selId(ctx)) || null;
    host.appendChild(_el('div', 'res-sec-title', sel ? t('result.t.detail_title') : t('result.t.summary_title')));
    if (!ctx.base || !ctx.quote) {
        const warn = _el('div', 'res-tc-unitwarn', t('result.t.unit_unknown'));
        warn.title = t('result.t.unit_unknown_hint');
        host.appendChild(warn);
    }

    if (!sel) {
        const ps = ctx.pageTrades;
        if (!ps.length) {
            host.appendChild(_el('div', 'res-tc-hint', t('result.t.none')));
            return;
        }
        const wins = ps.filter(x => Number(x.pnl) > 0).length;
        const losses = ps.filter(x => Number(x.pnl) < 0).length;
        const net = ps.reduce((s, x) => s + (Number(x.pnl) || 0), 0);
        const best = ps.reduce((a, x) => (a == null || Number(x.pnl) > Number(a.pnl) ? x : a), null);
        const worst = ps.reduce((a, x) => (a == null || Number(x.pnl) < Number(a.pnl) ? x : a), null);
        const gi = (x) => (x ? ` (#${ctx.trades.indexOf(x) + 1})` : '');
        host.appendChild(_el('div', 'res-tc-sub',
            t('result.t.range', { a: ctx.page * TRADE_PAGE + 1, b: ctx.page * TRADE_PAGE + ps.length })));
        const cells = [
            [t('result.t.wl', { w: wins, l: losses }), ''],
            [t('result.t.win_rate', { p: `${((wins / ps.length) * 100).toFixed(1)}%` }), ''],
            [t('result.t.net'), fmtNum(net), tone(net)],
            [t('result.t.avg'), fmtNum(net / ps.length), tone(net)],
            [t('result.t.best'), `${best ? fmtNum(best.pnl) : '—'}${gi(best)}`, tone(best ? best.pnl : null)],
            [t('result.t.worst'), `${worst ? fmtNum(worst.pnl) : '—'}${gi(worst)}`, tone(worst ? worst.pnl : null)],
        ];
        const sum = _el('div', 'res-tc-sum');
        cells.forEach(([k, v, cls]) => {
            const c = _el('div', 'res-tc-cell');
            c.appendChild(_el('span', 'k', k));
            if (v != null) c.appendChild(_el('span', `v ${cls || ''}`, v));
            sum.appendChild(c);
        });
        host.appendChild(sum);
        host.appendChild(_el('div', 'res-tc-hint', t('result.t.pick_hint')));
        return;
    }

    const idx = ctx.trades.indexOf(sel);
    const top = _el('div', 'res-tc-top');
    top.append(
        _el('span', 'res-tc-idx', `#${idx + 1}`),
        _el('span', `res-side ${sel.side === 'short' ? 'short' : 'long'}`,
            t(sel.side === 'short' ? 'result.t.short' : 'result.t.long')),
        _el('span', `res-tc-pnl ${tone(sel.pnl)}`,
            `${sel.pnl == null ? '—' : fmtNum(sel.pnl)} (${fmtPct(sel.pnl_pct)})`),
    );
    host.appendChild(top);
    const qtyUnit = ctx.base ? ` ${ctx.base}` : '';
    const ccyUnit = ctx.quote ? ` ${ctx.quote}` : '';
    const rows = [
        [t('result.t.entry'), `${_whenText(sel.entry_time, ctx.intraday)} · ${sel.entry_price == null ? '—' : fmtNum(sel.entry_price)}`],
        [t('result.t.exit'), `${_whenText(sel.exit_time, ctx.intraday)} · ${sel.exit_price == null ? '—' : fmtNum(sel.exit_price)}`],
        [t('result.t.holding'), _holdText(sel.holding_bars, ctx.tf)],
        [t('result.t.size'), `${sel.size == null ? '—' : fmtNum(sel.size, 4)}${qtyUnit}`],
        [t('result.t.notional'), `${sel.notional == null ? '—' : fmtMoney(sel.notional)}${ccyUnit}`],
        [t('result.t.fee'), `${sel.fee == null ? '—' : fmtMoney(sel.fee)}${ccyUnit}`],
    ];
    rows.forEach(([k, v]) => {
        const r = _el('div', 'res-tc-row');
        r.append(_el('span', 'k', k), _el('span', 'v', v));
        host.appendChild(r);
    });
    [[t('result.t.entry_reason'), sel.entry_reason], [t('result.t.exit_reason'), sel.exit_reason]]
        .forEach(([k, v]) => {
            const r = _el('div', 'res-tc-row res-tc-reason');
            r.appendChild(_el('span', 'k', k));
            const vv = _el('span', 'v');
            vv.appendChild(_el('code', null, v || '—'));
            r.appendChild(vv);
            host.appendChild(r);
        });
    const btn = _el('button', 'res-tc-btn', t('result.t.locate'));
    btn.addEventListener('click', () => {
        _locateTrade(sel);
    });
    host.appendChild(btn);
}

function _niceScale(mn, mx, count = 4) {
    if (!Number.isFinite(mn) || !Number.isFinite(mx)) return { lo: 0, hi: 1, ticks: [0, 1] };
    const pad = (mx - mn) * 0.06 || Math.abs(mx) * 0.1 || 1;
    const lo = mn - pad, hi = mx + pad;
    const raw = (hi - lo) / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) {
        ticks.push(Math.abs(v) < step * 1e-6 ? 0 : v);
    }
    if (lo < 0 && hi > 0 && !ticks.includes(0)) ticks.push(0);
    ticks.sort((a, b) => a - b);
    return { lo, hi, ticks };
}

function _axisText(v) {
    const n = Math.round(v);
    return Math.abs(n) >= 1000 ? n.toLocaleString('en-US') : String(n);
}

function _drawYAxis(svg, ticks, y, x0, x1, fmt) {
    ticks.forEach(v => {
        const yy = y(v);
        svg.appendChild(_svg('line', {
            x1: x0, y1: yy, x2: x1, y2: yy,
            class: `res-chart-grid${v === 0 ? ' zero' : ''}`,
        }));
        const lab = _svg('text', { x: x0 - 6, y: yy + 3, class: 'res-chart-label', 'text-anchor': 'end' });
        lab.textContent = (fmt || _axisText)(v);
        svg.appendChild(lab);
    });
}

function _pctAxisText(v) {
    return `${Math.round(v).toLocaleString('en-US')}%`;
}

// 取 <= ms 的最后一根权益值（没有则用首值）
function _equityAt(times, values, ms) {
    let lo = 0, hi = times.length - 1, hit = -1;
    while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (Number(times[mid]) <= ms) { hit = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return hit >= 0 ? Number(values[hit]) : Number(values[0]);
}

function _equityChart(ctx) {
    const eq = ctx.equity || {};
    const times = eq.times || [];
    const values = eq.values || [];
    const cash = Number(ctx.initialCash) || 0;
    if (!times.length || times.length !== values.length || cash <= 0) return null;
    const W = 420, H = 210, L = 52, R = 16, T = 14, B = 24;
    const pw = W - L - R, ph = H - T - B;
    const raw = values.map(v => (Number(v) / cash - 1) * 100);
    const sc = _niceScale(Math.min(0, ...raw), Math.max(0, ...raw), 8);
    const x = (i) => L + (times.length === 1 ? pw / 2 : (i / (times.length - 1)) * pw);
    const y = (v) => T + ph * ((sc.hi - v) / ((sc.hi - sc.lo) || 1));
    const svg = _svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'res-chart', role: 'img' });
    _drawYAxis(svg, sc.ticks, y, L, W - R, _pctAxisText);
    let line = '';
    raw.forEach((v, i) => { line += `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
    const area = `M${x(0).toFixed(1)},${y(0).toFixed(1)} `
        + raw.map((v, i) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
        + ` L${x(raw.length - 1).toFixed(1)},${y(0).toFixed(1)} Z`;
    svg.appendChild(_svg('path', { d: area, class: 'res-chart-area' }));
    svg.appendChild(_svg('path', { d: line, class: 'res-chart-line' }));
    [0, Math.floor(times.length / 2), times.length - 1].forEach((i) => {
        const lab = _svg('text', {
            x: x(i), y: H - 6, class: 'res-chart-label',
            'text-anchor': i === 0 ? 'start' : i === times.length - 1 ? 'end' : 'middle',
        });
        lab.textContent = formatTimeCN(Math.floor(Number(times[i]) / 1000), false, state.uiTimezone);
        svg.appendChild(lab);
    });
    const endLab = _svg('text', {
        x: W - R, y: Math.max(T + 8, y(raw[raw.length - 1]) - 6),
        class: 'res-chart-value', 'text-anchor': 'end',
    });
    endLab.textContent = fmtPct(raw[raw.length - 1] / 100);
    svg.appendChild(endLab);
    return svg;
}

function _cumChart(ctx) {
    const ts = ctx.trades;
    if (!ts.length) return null;
    const W = 420, H = 210, L = 52, R = 16, T = 14, B = 22;
    const pw = W - L - R, ph = H - T - B;
    const cash = Number(ctx.initialCash) || 0;
    const eq = ctx.equity || {};
    const eqT = eq.times || [];
    const eqV = eq.values || [];
    const useEq = cash > 0 && eqT.length > 0 && eqT.length === eqV.length;
    const usePct = cash > 0;
    let acc = 0;
    const pts = ts.map((tr, i) => {
        acc += Number(tr.pnl) || 0;
        const pct = useEq
            ? (_equityAt(eqT, eqV, Number(tr.exit_time)) / cash - 1)
            : (usePct ? acc / cash : null);
        return { i, v: acc, pct, t: tr };
    });
    const raw = pts.map(p => (usePct ? p.pct * 100 : p.v));
    const sc = _niceScale(Math.min(0, ...raw), Math.max(0, ...raw), 8);
    const x = (i) => L + (ts.length === 1 ? pw / 2 : (i / (ts.length - 1)) * pw);
    const y = (v) => T + ph * ((sc.hi - v) / ((sc.hi - sc.lo) || 1));
    const svg = _svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'res-chart', role: 'img' });
    _drawYAxis(svg, sc.ticks, y, L, W - R, usePct ? _pctAxisText : _axisText);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(raw[i]).toFixed(1)}`).join(' ');
    const area = `M${x(0).toFixed(1)},${y(0).toFixed(1)} `
        + pts.map((p, i) => `L${x(i).toFixed(1)},${y(raw[i]).toFixed(1)}`).join(' ')
        + ` L${x(pts.length - 1).toFixed(1)},${y(0).toFixed(1)} Z`;
    svg.appendChild(_svg('path', { d: area, class: 'res-chart-area' }));
    svg.appendChild(_svg('path', { d: line, class: 'res-chart-line' }));
    pts.forEach((p, i) => {
        const c = _svg('circle', { cx: x(i), cy: y(raw[i]), r: 6, class: 'res-chart-pt' });
        const ti = _svg('title');
        ti.textContent = `#${i + 1} · ${usePct ? fmtPct(p.pct) : fmtNum(p.v)}`;
        c.appendChild(ti);
        c.addEventListener('click', () => _selectTrade(p.t));
        svg.appendChild(c);
    });
    [0, Math.floor(pts.length / 2), pts.length - 1].forEach((i) => {
        const lab = _svg('text', {
            x: x(i), y: H - 6, class: 'res-chart-label',
            'text-anchor': i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle',
        });
        lab.textContent = String(i + 1);
        svg.appendChild(lab);
    });
    const last = pts[pts.length - 1];
    const endLab = _svg('text', {
        x: W - R, y: Math.max(T + 8, y(raw[raw.length - 1]) - 6),
        class: 'res-chart-value', 'text-anchor': 'end',
    });
    endLab.textContent = usePct ? fmtPct(last.pct) : fmtNum(last.v);
    svg.appendChild(endLab);
    return svg;
}

function _monthChart(ctx) {
    const ts = ctx.trades;
    if (!ts.length) return null;
    const groups = new Map();
    ts.forEach(tr => {
        const k = _monthKey(tr.exit_time);
        if (!groups.has(k)) groups.set(k, { k, sum: 0, n: 0, first: tr });
        const g = groups.get(k);
        g.sum += Number(tr.pnl) || 0;
        g.n += 1;
    });
    const arr = [...groups.values()].sort((a, b) => (a.k < b.k ? -1 : a.k > b.k ? 1 : 0));
    const W = 420, H = 210, L = 46, R = 10, T = 14, B = 24;
    const pw = W - L - R, ph = H - T - B;
    const vals = arr.map(g => g.sum);
    const sc = _niceScale(Math.min(0, ...vals), Math.max(0, ...vals), 6);
    const y = (v) => T + ph * ((sc.hi - v) / ((sc.hi - sc.lo) || 1));
    const svg = _svg('svg', { viewBox: `0 0 ${W} ${H}`, class: 'res-chart', role: 'img' });
    _drawYAxis(svg, sc.ticks, y, L, W - R);
    const bw = (pw / arr.length) * 0.58;
    const every = Math.max(1, Math.ceil(arr.length / 8));
    const zero = y(0);
    arr.forEach((g, i) => {
        const cx = L + (i + 0.5) * (pw / arr.length);
        const top = Math.min(y(g.sum), zero);
        const h = Math.max(1.5, Math.abs(y(g.sum) - zero));
        const bar = _svg('rect', {
            x: cx - bw / 2, y: top, width: bw, height: h, rx: 1.5,
            class: `res-chart-bar ${g.sum >= 0 ? 'up' : 'down'}`,
        });
        const ti = _svg('title');
        ti.textContent = `${g.k} · ${fmtNum(g.sum)} · ${g.n}`;
        bar.appendChild(ti);
        bar.addEventListener('click', () => _selectTrade(g.first));
        svg.appendChild(bar);
        if (i % every === 0) {
            const lab = _svg('text', { x: cx, y: H - 7, class: 'res-chart-label', 'text-anchor': 'middle' });
            lab.textContent = g.k.slice(2);
            svg.appendChild(lab);
        }
    });
    return svg;
}

function _renderTradeChart() {
    const ctx = _tradeCtx;
    const host = document.querySelector('#wb-overview .res-trade-chart-host');
    if (!ctx || !host) return;
    host.textContent = '';
    let svg = null;
    if (_tradeTab === 'cum') svg = _cumChart(ctx);
    else if (_tradeTab === 'month') svg = _monthChart(ctx);
    else svg = _equityChart(ctx);
    if (svg) host.appendChild(svg);
    else host.appendChild(_el('div', 'res-chart-empty', t('result.t.chart_empty')));
    const hint = document.querySelector('#wb-overview .res-chart-hint');
    if (hint) hint.textContent = _tradeTab === 'equity' ? t('result.t.equity_hint') : t('result.t.chart_hint');
}

function rememberScene() {
    SCENES[sceneKey()] = { visible: [...state.resultVisible], active: state.resultActive };
}

// v0.6.3 保留策略提示：让用户知道结果会被自动淘汰（不是静默删除）
let _retention = null;   // {limit,count,warn_at,evict_next} ← /api/results

function renderRetention() {
    const el = document.getElementById('result-retention');
    if (!el) return;
    const rt = _retention;
    const has = (state.results || []).length > 0;
    if (!rt || !has) {
        el.style.display = 'none';
        el.textContent = '';
        el.classList.remove('warn');
        return;
    }
    const n = Number(rt.limit) || 100;
    const c = Number(rt.count) || 0;
    el.style.display = '';
    el.title = t('result.retention_title', { n });
    if (c >= n) {
        el.textContent = t('result.retention_full', { c, n });
        el.classList.add('warn');
    } else if (c >= (Number(rt.warn_at) || n - 10)) {
        el.textContent = t('result.retention_warn', { c, n, left: n - c });
        el.classList.add('warn');
    } else {
        el.textContent = t('result.retention', { n });
        el.classList.remove('warn');
    }
}

export function clearResultsScene() {
    _syncSeq++;
    state.results = [];
    state.resultVisible = [];
    state.resultActive = null;
    state.resultDetail = {};
    renderResultBar();
    fillOverview();
    refreshResultLayer();
    renderWorkbench();
}

export async function syncResultsForScene() {
    const board = state.currentBoard, tf = state.currentTimeframe;
    if (!board || !tf) { clearResultsScene(); return; }
    const seq = ++_syncSeq;
    const url = `/api/results?board_id=${encodeURIComponent(board)}&timeframe=${encodeURIComponent(tf)}`;
    let data = null;
    try { data = await (await fetch(url)).json(); } catch (e) { data = null; }
    if (seq !== _syncSeq || sceneKey() !== `${board}|${tf}`) return;
    if (!data || data.error) { clearResultsScene(); return; }
    state.results = data.results || [];
    _retention = data.retention || null;
    const known = new Set(state.results.map(r => r.result_id));
    const mem = SCENES[sceneKey()];
    let vis = ((mem && mem.visible) || []).filter(id => known.has(id));
    if (!vis.length && state.results.length && !mem) vis = [state.results[0].result_id];
    state.resultVisible = vis;
    state.resultActive = (mem && mem.active && known.has(mem.active)) ? mem.active : (vis[0] || null);
    Object.keys(state.resultDetail || {}).forEach(id => { if (!known.has(id)) delete state.resultDetail[id]; });
    renderResultBar();
    fillOverview();
    renderWorkbench();
    updateWorkbenchStatus();
    await ensureDetails(vis);
    refreshResultLayer();
    renderResultBar();
    fillOverview();
}

async function ensureDetails(ids) {
    const wanted = (ids || []).filter(id => id && !(state.resultDetail || {})[id]);
    if (!wanted.length) return;
    await Promise.all(wanted.map(async (id) => {
        try {
            const [eq, tr] = await Promise.all([
                fetch(`/api/result/${encodeURIComponent(id)}?section=equity&limit=0`).then(r => r.json()),
                fetch(`/api/result/${encodeURIComponent(id)}?section=trades&limit=0`).then(r => r.json()),
            ]);
            const meta = (state.results || []).find(r => r.result_id === id) || {};
            state.resultDetail[id] = {
                summary: meta,
                equity: { times: eq.times || [], values: eq.values || [] },
                trades: tr.items || [],
            };
        } catch (e) {
            console.warn('[ak] result detail load failed:', id, e);
        }
    }));
}

export function selectResult(id) {
    if (!state.results.some(r => r.result_id === id)) return;
    if (!state.resultVisible.includes(id)) {
        if (state.resultVisible.length >= MAX_VISIBLE) state.resultVisible = state.resultVisible.slice(1);
        state.resultVisible = [...state.resultVisible, id];
    }
    state.resultActive = id;
    rememberScene();
    ensureDetails([id]).then(() => { refreshResultLayer(); fillOverview(); });
    refreshResultLayer();
    renderResultBar();
    fillOverview();
    renderWorkbench();
    updateWorkbenchStatus();
}

// × 只把结果移出图表（不删数据）；删除仍在右键菜单/概览按钮
export function hideResult(id) {
    if (!state.resultVisible.includes(id)) return;
    state.resultVisible = state.resultVisible.filter(x => x !== id);
    if (state.resultActive === id) state.resultActive = state.resultVisible[0] || null;
    rememberScene();
    refreshResultLayer();
    renderResultBar();
    fillOverview();
    renderWorkbench();
    updateWorkbenchStatus();
}

// Shift+单击：只叠到图上做对比，不切换当前详情
export function addCompare(id) {
    if (!state.results.some(r => r.result_id === id)) return;
    if (state.resultVisible.includes(id)) return;
    if (state.resultVisible.length >= MAX_VISIBLE) {
        addActivity('warn', t('result.too_many'));
        return;
    }
    state.resultVisible = [...state.resultVisible, id];
    if (!state.resultActive) state.resultActive = id;
    rememberScene();
    ensureDetails([id]).then(() => { refreshResultLayer(); renderResultBar(); fillOverview(); });
    refreshResultLayer();
    renderResultBar();
    fillOverview();
    renderWorkbench();
    updateWorkbenchStatus();
}

export async function deleteResult(id) {
    const r = (state.results || []).find(x => x.result_id === id);
    if (!r) return;
    const yes = await openDialog({
        title: t('result.delete'),
        message: t('result.delete_confirm'),
        confirmText: t('result.delete'),
        danger: true,
    });
    if (!yes) return;
    try {
        const resp = await fetch(`/api/result/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error(String(resp.status));
    } catch (e) {
        addActivity('error', `${t('result.delete')} ${id}: ${e.message}`);
        return;
    }
    state.results = state.results.filter(x => x.result_id !== id);
    state.resultVisible = state.resultVisible.filter(x => x !== id);
    delete state.resultDetail[id];
    if (state.resultActive === id) state.resultActive = state.resultVisible[0] || null;
    rememberScene();
    refreshResultLayer();
    renderResultBar();
    fillOverview();
    renderWorkbench();
    updateWorkbenchStatus();
}

export async function renameResult(id) {
    const r = (state.results || []).find(x => x.result_id === id);
    if (!r) return;
    const name = await openDialog({
        title: t('result.rename'),
        placeholder: t('result.rename_prompt'),
        value: r.display_name || id,
        confirmText: t('common.ok'),
    });
    if (name == null || !name.trim()) return;
    try {
        const resp = await fetch(`/api/result/${encodeURIComponent(id)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: name.trim() }),
        });
        if (!resp.ok) throw new Error(String(resp.status));
    } catch (e) {
        addActivity('error', `${t('result.rename')}: ${e.message}`);
        return;
    }
    r.display_name = name.trim();
    if (state.resultDetail[id]) state.resultDetail[id].summary = r;
    addActivity('result', `${t('result.rename')} → ${r.display_name}`, { resultId: id });
    renderResultBar();
    fillOverview();
    refreshResultLayer();
}

function _csvCell(v) {
    if (v == null) return '';
    const str = String(v);
    return /[",\n\r]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

// 交易明细 CSV：全部交易（不分页），UTF-8 BOM 便于 Excel 直接打开
export function exportTradesCsv() {
    const ctx = _tradeCtx;
    if (!ctx || !ctx.trades.length) return false;
    const head = ['no', 'side', 'entry_time', 'entry_price', 'exit_time', 'exit_price',
                  'holding_bars', 'size', 'notional', 'fee', 'pnl', 'pnl_pct',
                  'entry_reason', 'exit_reason'];
    const rows = ctx.trades.map((tr, i) => [
        i + 1, tr.side, tr.entry_time, tr.entry_price, tr.exit_time, tr.exit_price,
        tr.holding_bars, tr.size, tr.notional, tr.fee, tr.pnl, tr.pnl_pct,
        tr.entry_reason, tr.exit_reason,
    ]);
    const text = [head, ...rows].map(r => r.map(_csvCell).join(',')).join('\r\n');
    const blob = new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = activeSummary();
    const base = ((a && (a.display_name || a.result_id)) || 'result').replace(/[\\/:*?"<>|]/g, '_');
    const link = document.createElement('a');
    link.href = url;
    link.download = `${base}_${state.currentTimeframe}_trades.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
}

export function renderResultBar() {
    const bar = document.getElementById('result-bar');
    const chips = document.getElementById('result-chips');
    const stats = document.getElementById('result-stats');
    if (!bar || !chips || !stats) return;
    bar.style.display = '';
    renderRetention();
    chips.textContent = '';
    state.results.forEach(r => {
        const id = r.result_id;
        const vis = state.resultVisible.includes(id);
        const chip = _el('div', `res-chip${vis ? ' on' : ''}${id === state.resultActive ? ' active' : ''}`);
        chip.dataset.id = id;
        const dot = _el('span', 'res-dot');
        dot.style.background = resultColor(id);
        const name = _el('span', 'res-name', r.display_name || id);
        const pct = _el('span', `res-pct ${tone(r.stats && r.stats.total_return)}`, fmtPct(r.stats && r.stats.total_return));
        const x = _el('span', 'res-x', '×');
        x.title = t('result.remove_from_chart');
        x.addEventListener('click', (e) => { e.stopPropagation(); hideResult(id); });
        chip.append(dot, name, pct, x);
        chip.title = `${statusLabel(r.status)} · ${(r.data && r.data.timeframe) || ''} · ${(r.data && r.data.actual && r.data.actual.bars) || 0} ${t('result.bars')}\n${t('result.chip_hint')}`;
        chip.addEventListener('click', (e) => {
            if (e.shiftKey) addCompare(id);
            else selectResult(id);
        });
        chip.addEventListener('dblclick', () => openWorkbench('overview'));
        chip.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            showContextMenu(e.clientX, e.clientY, [
                { label: t('result.detail'), onClick: () => { selectResult(id); openWorkbench('overview'); } },
                { label: t('result.rename'), onClick: () => renameResult(id) },
                { label: t('result.delete'), danger: true, onClick: () => deleteResult(id) },
            ]);
        });
        chips.appendChild(chip);
    });

    stats.textContent = '';
    const a = activeSummary();
    if (!a) {
        stats.appendChild(_el('span', 'res-stat-empty', t('result.none')));
        const btn0 = document.getElementById('result-detail');
        if (btn0) btn0.style.display = 'none';
        return;
    }
    const s = a.stats || {};
    const rows = [
        [t('result.m.total_return'), fmtPct(s.total_return), tone(s.total_return)],
        [t('result.m.mdd'), fmtPct(s.max_drawdown), tone(s.max_drawdown)],
        [t('result.m.sharpe'), fmtNum(s.sharpe), ''],
        [t('result.m.win'), fmtPctPlain(s.win_rate), ''],
        [t('result.m.trades'), String(s.trade_count == null ? 0 : s.trade_count), ''],
    ];
    rows.forEach(([k, v, cls]) => {
        const item = _el('span', 'res-stat');
        item.append(_el('span', 'k', k), _el('span', `v ${cls}`, v));
        stats.appendChild(item);
    });
    const btn = document.getElementById('result-detail');
    if (btn) {
        btn.style.display = a ? '' : 'none';
        btn.onclick = () => openWorkbench('overview');
    }
}

function _metricRows(s) {
    return [
        [t('result.m.total_return'), fmtPct(s.total_return), tone(s.total_return)],
        [t('result.m.annual'), fmtPct(s.annual_return), tone(s.annual_return)],
        [t('result.m.mdd'), fmtPct(s.max_drawdown), tone(s.max_drawdown)],
        [t('result.m.sharpe'), fmtNum(s.sharpe), ''],
        [t('result.m.sortino'), fmtNum(s.sortino), ''],
        [t('result.m.win'), fmtPctPlain(s.win_rate), ''],
        [t('result.m.pl'), s.profit_loss_ratio == null ? '—' : fmtNum(s.profit_loss_ratio), ''],
        [t('result.m.pf'), s.profit_factor == null ? '—' : fmtNum(s.profit_factor), ''],
        [t('result.m.trades'), String(s.trade_count == null ? 0 : s.trade_count), ''],
        [t('result.m.holding'), s.avg_holding_bars == null ? '—' : fmtNum(s.avg_holding_bars, 1), ''],
        [t('result.m.exposure'), fmtPctPlain(s.exposure), ''],
        [t('result.m.fees'), fmtNum(s.total_fees), ''],
        [t('result.m.final'), fmtNum(s.final_value), ''],
        [t('result.m.benchmark'), s.benchmark_return == null ? '—' : fmtPct(s.benchmark_return), ''],
        [t('result.m.excess'), s.excess_return == null ? '—' : fmtPct(s.excess_return), tone(s.excess_return)],
    ];
}

export function fillOverview() {
    const el = document.getElementById('wb-overview');
    if (!el) return;
    el.textContent = '';
    const a = activeSummary();
    if (!a) {
        const empty = _el('div', 'wb-empty', t('result.empty'));
        el.appendChild(empty);
        return;
    }
    const d = (state.resultDetail || {})[a.result_id] || {};
    const head = _el('div', 'res-ov-head');
    head.append(
        _el('span', 'res-ov-name', a.display_name || a.result_id),
        _el('span', `res-badge status-${a.status}`, statusLabel(a.status)),
        _el('span', 'res-ov-sub', `${a.strategy && a.strategy.id ? a.strategy.id : ''} · ${a.engine && a.engine.id ? a.engine.id : ''}`),
    );
    const actions = _el('div', 'res-ov-actions');
    const rb = _el('button', 'btn-ghost', t('result.rename'));
    rb.addEventListener('click', () => renameResult(a.result_id));
    const db = _el('button', 'btn-ghost danger', t('result.delete'));
    db.addEventListener('click', () => deleteResult(a.result_id));
    actions.append(rb, db);
    head.appendChild(actions);
    el.appendChild(head);

    const win = (a.run && a.run.window) || {};
    const winLine = _el('div', 'res-ov-window',
        `${t('result.window')} ${win.from ? formatTimeCN(Math.floor(win.from / 1000), false, state.uiTimezone) : '—'} → ${win.to ? formatTimeCN(Math.floor(win.to / 1000), false, state.uiTimezone) : '—'} · ${win.bars || 0} ${t('result.bars')}`);
    el.appendChild(winLine);

    const grid = _el('div', 'res-metrics');
    _metricRows(a.stats || {}).forEach(([k, v, cls]) => {
        const cell = _el('div', 'res-metric');
        cell.append(_el('span', 'k', k), _el('span', `v ${cls}`, v));
        grid.appendChild(cell);
    });
    el.appendChild(grid);

    const listTrades = d.trades;
    if (Array.isArray(listTrades)) {
        const rid = a.result_id;
        const pageCount = Math.max(1, Math.ceil(listTrades.length / TRADE_PAGE));
        const page = Math.min(Math.max(_tradePage[rid] || 0, 0), pageCount - 1);
        _tradePage[rid] = page;
        const pageTrades = listTrades.slice(page * TRADE_PAGE, (page + 1) * TRADE_PAGE);
        const intraday = isIntraday(state.currentTimeframe);
        const units = _unitsOf(a);
        _tradeCtx = {
            rid, trades: listTrades, page, pageTrades,
            tf: state.currentTimeframe, intraday,
            base: units.base, quote: units.quote,
            initialCash: Number(a.run && a.run.initial_cash) || 0,
            equity: d.equity || null,
        };

        const det = document.createElement('details');
        det.className = 'res-trades';
        det.open = _tradesOpen;
        det.addEventListener('toggle', () => {
            _tradesOpen = det.open;
            try { localStorage.setItem('ak_trade_open', det.open ? '1' : '0'); } catch (e) { /* 忽略 */ }
        });
        const sum = _el('summary', null, t('result.trades_detail'));
        sum.appendChild(_el('span', 'res-trades-count', t('result.t.count', { n: listTrades.length })));
        const csv = _el('button', 'res-csv-btn', 'CSV');
        csv.type = 'button';
        csv.title = t('result.t.csv_hint');
        csv.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            exportTradesCsv();
        });
        sum.appendChild(csv);
        if (!units.base || !units.quote) {
            const warn = _el('span', 'res-trades-unitwarn', t('result.t.unit_unknown'));
            warn.title = t('result.t.unit_unknown_hint');
            sum.appendChild(warn);
        }
        det.appendChild(sum);

        const grid = _el('div', 'res-trade-grid');

        // ① 交易列表
        const listCol = _el('div', 'res-trade-col res-trade-list');
        if (!listTrades.length) {
            listCol.appendChild(_el('div', 'res-trades-empty', t('result.t.none')));
        } else {
            const table = document.createElement('table');
            const hr = document.createElement('tr');
            [[t('result.t.no'), 'num'], [t('result.t.side'), ''], [t('result.t.entry'), ''],
             [t('result.t.exit'), ''], [t('result.t.holding'), 'num'], [t('result.t.pnl'), 'num']]
                .forEach(([h, cls]) => hr.appendChild(_el('th', cls, h)));
            table.appendChild(hr);
            pageTrades.forEach((tr, i) => {
                const row = document.createElement('tr');
                row.className = `res-trade-row${Number(tr.pnl) < 0 ? ' loss' : ''}`;
                row.tabIndex = 0;
                row.dataset.tid = _tid(tr);
                row.title = t('result.t.jump_hint');
                row.appendChild(_el('td', 'num', String(page * TRADE_PAGE + i + 1)));
                const side = _el('td', null, '');
                side.appendChild(_el('span', `res-side ${tr.side === 'short' ? 'short' : 'long'}`,
                    t(tr.side === 'short' ? 'result.t.short' : 'result.t.long')));
                row.appendChild(side);
                row.appendChild(_tradeTimeCell(tr.entry_time, tr.entry_price, intraday));
                row.appendChild(_tradeTimeCell(tr.exit_time, tr.exit_price, intraday));
                const hold = _el('td', 'num', _holdText(tr.holding_bars, state.currentTimeframe));
                if (tr.holding_bars != null) hold.title = t('result.t.holding_bars', { n: tr.holding_bars });
                row.appendChild(hold);
                const pnl = _el('td', `num res-t-pnl ${tone(tr.pnl)}`, '');
                pnl.append(_el('div', 'v', tr.pnl == null ? '—' : fmtNum(tr.pnl)),
                           _el('div', 'p', fmtPct(tr.pnl_pct)));
                row.appendChild(pnl);
                row.addEventListener('click', () => _selectTrade(tr, true));
                row.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _selectTrade(tr, true); }
                });
                table.appendChild(row);
            });
            // 不满一页时补空行，保证列表与右侧卡片同高、翻页时高度不跳
            for (let i = pageTrades.length; i < TRADE_PAGE; i++) {
                const pad = document.createElement('tr');
                pad.className = 'res-trade-row-pad';
                pad.setAttribute('aria-hidden', 'true');
                for (let c = 0; c < 6; c++) pad.appendChild(_el('td', null, ''));
                table.appendChild(pad);
            }
            listCol.appendChild(table);
            // 翻页条常驻：不满一页也显示「第 1 / 1 页」，列表高度不随页数跳
            if (pageCount > 0) {
                const pager = _el('div', 'res-pager');
                const prev = _el('button', 'res-page-btn', '‹');
                prev.disabled = page <= 0;
                prev.title = t('result.t.prev');
                prev.addEventListener('click', () => {
                    _tradePage[rid] = page - 1;
                    delete _tradeSel[rid];
                    state.resultSelTrade = '';
                    fillOverview();
                });
                const next = _el('button', 'res-page-btn', '›');
                next.disabled = page >= pageCount - 1;
                next.title = t('result.t.next');
                next.addEventListener('click', () => {
                    _tradePage[rid] = page + 1;
                    delete _tradeSel[rid];
                    state.resultSelTrade = '';
                    fillOverview();
                });
                pager.append(prev, _el('span', 'res-page-info', t('result.t.page', { i: page + 1, n: pageCount })), next);
                listCol.appendChild(pager);
            }
        }
        grid.appendChild(listCol);

        // ② 单笔详情 / 本页小结
        grid.appendChild(_el('div', 'res-trade-col res-trade-detail'));

        // ③ 图（选项卡）
        const chartCol = _el('div', 'res-trade-col res-trade-chart');
        const tabs = _el('div', 'res-trade-tabs');
        [['equity', t('result.t.tab_equity')], ['cum', t('result.t.tab_cum')], ['month', t('result.t.tab_month')]]
            .forEach(([key, label]) => {
                const b = _el('button', `res-trade-tab${_tradeTab === key ? ' on' : ''}`, label);
                b.addEventListener('click', () => {
                    _tradeTab = key;
                    try { localStorage.setItem('ak_trade_tab', key); } catch (e) { /* 忽略 */ }
                    [...tabs.children].forEach(x => x.classList.toggle('on', x === b));
                    _renderTradeChart();
                });
                tabs.appendChild(b);
            });
        chartCol.append(tabs, _el('div', 'res-trade-chart-host'), _el('div', 'res-chart-hint', t('result.t.chart_hint')));
        grid.appendChild(chartCol);

        det.appendChild(grid);
        el.appendChild(det);

        _renderTradeDetail();
        _renderTradeChart();
    }

    if ((a.warnings || []).length) {
        const warn = _el('div', 'res-warn');
        warn.appendChild(_el('div', 'res-warn-title', t('result.warnings')));
        a.warnings.forEach(w => warn.appendChild(_el('div', 'res-warn-line', `· ${w}`)));
        el.appendChild(warn);
    }

    const vis = (state.results || []).filter(r => state.resultVisible.includes(r.result_id));
    if (vis.length > 1) {
        const cmp = _el('div', 'res-compare');
        cmp.appendChild(_el('div', 'res-sec-title', t('result.compare')));
        const table = document.createElement('table');
        const hr = document.createElement('tr');
        [t('result.compare.name'), t('result.m.total_return'), t('result.m.mdd'), t('result.m.sharpe'), t('result.m.trades'), '']
            .forEach(h => hr.appendChild(_el('th', null, h)));
        table.appendChild(hr);
        // 差异高亮：每列取最优（收益/夏普越高越好，回撤越接近 0 越好），只在 ≥2 条时标
        const nums = vis.map(r => r.stats || {});
        const bestOf = (key) => {
            const vals = nums.map(s => Number(s[key])).filter(Number.isFinite);
            return vals.length >= 2 ? Math.max(...vals) : null;
        };
        const bestRet = bestOf('total_return'), bestMdd = bestOf('max_drawdown'), bestSharpe = bestOf('sharpe');
        const cellCls = (v, best) => (best != null && Number.isFinite(Number(v)) && Number(v) === best ? 'best' : '');
        vis.forEach(r => {
            const tr = document.createElement('tr');
            const s = r.stats || {};
            tr.appendChild(_el('td', null, r.display_name || r.result_id));
            tr.appendChild(_el('td', `${tone(s.total_return)} ${cellCls(s.total_return, bestRet)}`.trim(), fmtPct(s.total_return)));
            tr.appendChild(_el('td', `${tone(s.max_drawdown)} ${cellCls(s.max_drawdown, bestMdd)}`.trim(), fmtPct(s.max_drawdown)));
            tr.appendChild(_el('td', cellCls(s.sharpe, bestSharpe), fmtNum(s.sharpe)));
            tr.appendChild(_el('td', null, String(s.trade_count == null ? 0 : s.trade_count)));
            const xd = _el('td', 'res-cmp-x', '');
            const x = _el('span', 'res-x', '×');
            x.title = t('result.remove_from_chart');
            x.addEventListener('click', (e) => { e.stopPropagation(); hideResult(r.result_id); });
            xd.appendChild(x);
            tr.appendChild(xd);
            table.appendChild(tr);
        });
        cmp.appendChild(table);
        el.appendChild(cmp);
    }

    const trust = document.createElement('details');
    trust.className = 'res-trust';
    trust.open = _trustOpen;
    trust.addEventListener('toggle', () => { _trustOpen = trust.open; });
    const sum = _el('summary', null, t('result.trust'));
    sum.appendChild(_el('span', 'res-trust-hint', _trustHint(a)));
    trust.appendChild(sum);
    const body = _el('div', 'res-trust-body');

    const q = (a.data && a.data.quality) || {};
    body.appendChild(_el('div', 'res-sec-title', t('result.quality')));
    body.appendChild(_el('div', 'res-kv', _qualityLine(q)));
    (q.notes || []).forEach(n => body.appendChild(_el('div', 'res-kv dim', `· ${n}`)));

    const asm = a.execution_assumptions || {};
    body.appendChild(_el('div', 'res-sec-title', t('result.assumptions')));
    Object.entries(asm).forEach(([k, v]) => {
        if (k === 'notes') {
            (v || []).forEach(n => body.appendChild(_el('div', 'res-kv dim', `· ${n}`)));
        } else if (v != null) {
            body.appendChild(_el('div', 'res-kv', `${_asmLabel(k)}：${_asmValue(k, v)}`));
        }
    });

    const repro = a.reproducibility || {};
    body.appendChild(_el('div', 'res-sec-title', t('result.hashes')));
    Object.entries(repro).forEach(([k, v]) => {
        if (!v) return;
        const row = _el('div', 'res-kv mono', `${HASH_LABEL[k] ? t(HASH_LABEL[k]) : k}：${_shortHash(v)}`);
        row.title = String(v);
        body.appendChild(row);
    });

    trust.appendChild(body);
    el.appendChild(trust);
}

// 图上交易点点击（0.6.2 B1，B2-fix 改为「交易盒内」命中）：
// Vela 的 labels 没有官方点击回调，这里用「十字线所在 bar 时间 + 十字线价格 + 容器 click」做命中；
// 盒子的对角 = 买点(entry_time, entry_price) / 卖点(exit_time, exit_price)，与图上画的矩形完全一致，
// 因此点在盒子里的任意位置都算选中，盒外（含上方/下方空白）不再误触。
export function onChartBarClick(timeMs, priceMs) {
    const a = activeSummary();
    if (!a || timeMs == null) return false;
    const d = (state.resultDetail || {})[a.result_id] || {};
    const trades = Array.isArray(d.trades) ? d.trades : [];
    if (!trades.length) return false;
    const inBox = (tr) => {
        const t0 = Number(tr.entry_time), t1 = Number(tr.exit_time);
        if (!Number.isFinite(t0) || !Number.isFinite(t1)) return false;
        if (Number(timeMs) < t0 || Number(timeMs) > t1) return false;
        const p0 = Number(tr.entry_price), p1 = Number(tr.exit_price);
        // 拿不到十字线价格时退回「只按时间」，保证键盘/无指针场景仍可用
        if (!Number.isFinite(priceMs) || !Number.isFinite(p0) || !Number.isFinite(p1)) return true;
        return Number(priceMs) >= Math.min(p0, p1) && Number(priceMs) <= Math.max(p0, p1);
    };
    const hits = trades.filter(inBox);
    if (!hits.length) return false;
    // 嵌套/重叠时取最短的那笔（内层优先）
    hits.sort((x, y) => (Number(x.exit_time) - Number(x.entry_time))
        - (Number(y.exit_time) - Number(y.entry_time)));
    return _openTrade(a, trades, hits[0]);
}

// 选中一笔并打开概览详情（图点击/表点击共用）
function _openTrade(a, trades, hit) {
    const idx = trades.indexOf(hit);
    if (idx < 0) return false;
    _tradePage[a.result_id] = Math.floor(idx / TRADE_PAGE);
    _tradeSel[a.result_id] = _tid(hit);
    state.resultSelTrade = _tid(hit);
    _tradesOpen = true;
    openWorkbench('overview');
    fillOverview();
    const _t0 = performance.now();
    refreshResultMarksOnly();
    try { window.__akSelMs = performance.now() - _t0; } catch (e) { /* 计时把手 */ }
    const host = document.querySelector('#wb-overview .res-trade-detail');
    if (host && host.scrollIntoView) host.scrollIntoView({ block: 'nearest' });
    return true;
}

function _activeTrades() {
    const a = activeSummary();
    if (!a) return [];
    const d = (state.resultDetail || {})[a.result_id] || {};
    return Array.isArray(d.trades) ? d.trades : [];
}

// 图上点击总入口：先按 B/S 标记 ±6px 命中，再退到「交易盒内」命中
export function onChartClick(clientX, clientY, timeMs, price) {
    const a = activeSummary();
    if (!a) return false;
    const trades = _activeTrades();
    if (!trades.length) return false;
    const mk = hitTradeMarker(clientX, clientY, trades);
    if (mk) {
        try { window.__akMarkerHits = (window.__akMarkerHits || 0) + 1; } catch (e) { /* 调试计数 */ }
        return _openTrade(a, trades, mk);
    }
    // 只有带价格（点在主图价格区）才做盒命中；其它 pane 的点击按“空白”处理
    if (Number.isFinite(price) && onChartBarClick(timeMs, price)) return true;
    // 点空白（不在任何盒子/标记上）= 取消选中，详情回到本页小结
    return clearTradeSelection();
}

// 取消选中：清掉行高亮与结果层描边，详情回到小结
export function clearTradeSelection() {
    const a = activeSummary();
    if (!a || !state.resultSelTrade) return false;
    const rid = a.result_id;
    state.resultSelTrade = '';
    delete _tradeSel[rid];
    document.querySelectorAll('#wb-overview .res-trade-row.sel').forEach(r => r.classList.remove('sel'));
    _renderTradeDetail();
    refreshResultMarksOnly();
    return true;
}

try {
    window.__akChartClick = (ms, price) => onChartBarClick(ms, price);
    window.__akMarkerPoints = () => tradeMarkerPoints(_activeTrades());
    window.__akHitTest = (x, y) => hitTradeMarker(x, y, _activeTrades());
    window.__akSelTrade = () => state.resultSelTrade || '';
} catch (e) { /* 调试把手 */ }

export function onResultEvent(msg) {
    const r = msg.result || {};
    const bid = msg.board_id || (r.data && r.data.board);
    const tf = msg.timeframe || (r.data && r.data.timeframe);
    // v0.6.3：结果被自动淘汰必须让人看见（跨画板也提示，不静默丢东西）
    if (msg.type === 'result_deleted' && msg.evicted) {
        toast(t('result.evicted', {
            name: msg.display_name || msg.result_id,
            n: Number(msg.limit) || (_retention && _retention.limit) || 100,
        }));
    }
    if (bid !== state.currentBoard || tf !== state.currentTimeframe) return;
    if (msg.type === 'result_created' && r.result_id) {
        state.results = [r, ...(state.results || []).filter(x => x.result_id !== r.result_id)];
        _retention = { ...(_retention || { limit: 100, warn_at: 90 }), count: state.results.length };
        if (!state.resultVisible.includes(r.result_id) && state.resultVisible.length < MAX_VISIBLE) {
            state.resultVisible = [...state.resultVisible, r.result_id];
        }
        state.resultActive = r.result_id;
        rememberScene();
        renderResultBar();
        fillOverview();
        renderWorkbench();
        updateWorkbenchStatus();
        ensureDetails([r.result_id]).then(() => {
            refreshResultLayer();
            renderResultBar();
            fillOverview();
        });
    } else if (msg.type === 'result_updated' && r.result_id) {
        state.results = (state.results || []).map(x => x.result_id === r.result_id ? r : x);
        if (state.resultDetail[r.result_id]) state.resultDetail[r.result_id].summary = r;
        renderResultBar();
        fillOverview();
        refreshResultLayer();
    } else if (msg.type === 'result_deleted' && msg.result_id) {
        state.results = (state.results || []).filter(x => x.result_id !== msg.result_id);
        _retention = { ...(_retention || { limit: 100, warn_at: 90 }), count: state.results.length };
        state.resultVisible = state.resultVisible.filter(x => x !== msg.result_id);
        delete state.resultDetail[msg.result_id];
        if (state.resultActive === msg.result_id) state.resultActive = state.resultVisible[0] || null;
        rememberScene();
        refreshResultLayer();
        renderResultBar();
        fillOverview();
        renderWorkbench();
        updateWorkbenchStatus();
    }
}

export function bindResults() {
    window.addEventListener('ak:open-result', (e) => {
        const id = e.detail && e.detail.id;
        if (id) { selectResult(id); openWorkbench('overview'); }
    });
    const addBt = document.getElementById('result-add');
    if (addBt) addBt.addEventListener('click', () => { openBacktestDialog(); });
    renderResultBar();
    fillOverview();
}
