// Vela PoC 共享 mock 数据（ seeded 随机游走，可复现）
(function (global) {
    function mulberry32(a) {
        return function () {
            a |= 0; a = (a + 0x6D2B79F5) | 0;
            let t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }
    const rnd = mulberry32(20261003);
    const DAY = 86400;
    const N = 500;
    const t0 = Math.floor(Date.UTC(2024, 0, 1) / 1000);

    // OHLCV：趋势段 + 震荡段交替
    const ohlcv = [];
    let price = 30000;
    for (let i = 0; i < N; i++) {
        const phase = Math.floor(i / 100) % 2;           // 0=趋势 1=震荡
        const drift = phase === 0 ? (Math.floor(i / 100) % 4 < 2 ? 0.004 : -0.003) : 0;
        const vol = phase === 0 ? 0.02 : 0.012;
        const open = price;
        const chg = drift + (rnd() - 0.5) * 2 * vol;
        const close = Math.max(1000, open * (1 + chg));
        const high = Math.max(open, close) * (1 + rnd() * 0.008);
        const low = Math.min(open, close) * (1 - rnd() * 0.008);
        const volume = 500 + rnd() * 2000 * (1 + Math.abs(chg) * 40);
        ohlcv.push({ time: (t0 + i * DAY) * 1000, open, high, low, close, volume });
        price = close;
    }

    // 双均线（fast=10 / slow=30）
    function sma(arr, n) {
        const out = [];
        let acc = 0;
        for (let i = 0; i < arr.length; i++) {
            acc += arr[i].close;
            if (i >= n) acc -= arr[i - n].close;
            out.push(i >= n - 1 ? acc / n : null);
        }
        return out;
    }
    const fast = sma(ohlcv, 10), slow = sma(ohlcv, 30);

    // equity 曲线（含回撤段）+ 归一化对比线（buy&hold 归一到 equity 首值）
    const equity = [], norm = [];
    let eq = 10000;
    const firstClose = ohlcv[0].close;
    for (let i = 0; i < N; i++) {
        const r = (ohlcv[i].close / ohlcv[i].open - 1);
        const pos = i % 97 < 60 ? 1 : 0;                 // 持仓窗口内才吃收益
        eq *= 1 + r * (pos ? 1.5 : 0) - 0.0004;
        equity.push(eq);
        norm.push(10000 * (ohlcv[i].close / firstClose));
    }
    // peak 线（underwater 填充上沿）
    const peak = [];
    let mx = -Infinity;
    for (let i = 0; i < N; i++) { mx = Math.max(mx, equity[i]); peak.push(mx); }

    function toPoints(vals) {
        return vals.map((v, i) => ({ time: ohlcv[i].time, value: v == null ? null : +v.toFixed(2) }));
    }

    // 持仓区间 + 交易点
    const positions = [{ from: 60, to: 140 }, { from: 210, to: 300 }, { from: 380, to: 460 }];
    const trades = [
        { idx: 60, side: 'buy', reason: 'MACD 金叉 + 放量突破 20 日高' },
        { idx: 140, side: 'sell', reason: '趋势线跌破止损' },
        { idx: 210, side: 'buy', reason: '回踩 EMA30 企稳' },
        { idx: 300, side: 'sell', reason: '目标位止盈 R=2.5' },
        { idx: 380, side: 'buy', reason: '底背离 + 资金流转正' },
        { idx: 460, side: 'sell', reason: '移动止盈触发' },
    ].map(t => ({ time: ohlcv[t.idx].time, price: ohlcv[t.idx].close, side: t.side, reason: t.reason }));

    global.MOCK = {
        ohlcv, DAY_MS: DAY * 1000,
        fast: toPoints(fast), slow: toPoints(slow),
        equity: toPoints(equity), norm: toPoints(norm), peak: toPoints(peak),
        positions, trades,
    };
})(window);
