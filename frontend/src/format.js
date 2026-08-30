    // ============================================================
    // 时间格式化（中国习惯）
    // ============================================================
    function isIntraday(tf) {
        // 1m/5m/15m/30m/1h/4h 等为日内，1d/1w/1M 为日线以上
        return /(m|h)$/i.test(tf || '');
    }

    function formatTimeCN(timeSec, showTime) {
        const d = new Date(timeSec * 1000);
        const y = d.getFullYear();
        const mo = String(d.getMonth() + 1).padStart(2, '0');
        const da = String(d.getDate()).padStart(2, '0');
        if (!showTime) return `${y}-${mo}-${da}`;
        const hh = String(d.getHours()).padStart(2, '0');
        const mi = String(d.getMinutes()).padStart(2, '0');
        return `${y}-${mo}-${da} ${hh}:${mi}`;
    }

export { isIntraday, formatTimeCN };
