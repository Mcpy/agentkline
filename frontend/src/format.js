    // ============================================================
    // 时间格式化（中国习惯）
    // ============================================================
    function isIntraday(tf) {
        // 1m/5m/15m/30m/1h/4h 等为日内，1d/1w/1M 为日线以上
        // 区分 1m（分钟）与 1M（月）：不能带 i 标志
        return /(m|h)$/.test(tf || '');
    }

    // timeZone：IANA 名称；空/`browser` = 跟随本机。图表轴、OHLC 读数、状态条共用。
    function formatTimeCN(timeSec, showTime, timeZone) {
        const d = new Date(timeSec * 1000);
        const opts = { year: 'numeric', month: '2-digit', day: '2-digit' };
        if (showTime) { opts.hour = '2-digit'; opts.minute = '2-digit'; opts.hour12 = false; }
        let tz = null;
        if (timeZone && timeZone !== 'browser') {
            try { new Intl.DateTimeFormat('en-US', { timeZone }).format(d); tz = timeZone; } catch (e) { tz = null; }
        }
        if (tz) opts.timeZone = tz;
        // sv-SE = ISO 风格：YYYY-MM-DD / YYYY-MM-DD HH:mm
        return new Intl.DateTimeFormat('sv-SE', opts).format(d);
    }

    // 只要时:分（动态流/日志用）；时区同界面
    function formatClock(ms, timeZone) {
        const opts = { hour: '2-digit', minute: '2-digit', hour12: false };
        if (timeZone && timeZone !== 'browser') {
            try { new Intl.DateTimeFormat('en-US', { timeZone }).format(new Date(ms)); opts.timeZone = timeZone; } catch (e) {}
        }
        return new Intl.DateTimeFormat('sv-SE', opts).format(new Date(ms));
    }

export { isIntraday, formatTimeCN, formatClock };
