import { state } from './state.js';
import { openSearch } from './search.js';
import { isIntraday, formatTimeCN } from './format.js';
import { log } from './log.js';
import { LightweightCharts } from './lwc.js';
import { openSettings } from './settings.js';
import { showContextMenu } from './menu.js';
import { attachDrawingInteraction } from './draw_interact.js';

// ============ v0.4.1 优化：K 线随雷达抽屉开闭自适应 ============
const _charts = [];   // [{chart, el}] 所有活体图表；renderChart 重建时重置

function _registerChart(chart, el) {
    _charts.push({ chart, el });
    return chart;
}

export function resizeAllCharts() {
    _charts.forEach(({ chart, el }) => {
        const w = el && (el.clientWidth || el.offsetWidth);
        if (!w) return;
        try { chart.applyOptions({ width: w }); } catch (e) { /* 已销毁的图表忽略 */ }
    });
}

let _ro = null;
function _ensureResizeObserver() {
    if (_ro || typeof ResizeObserver === 'undefined') return;
    const host = document.querySelector('.chart-container');
    if (!host) return;
    _ro = new ResizeObserver(() => resizeAllCharts());
    _ro.observe(host);
}

    // 显示名优先（自动/自定义），回退内部 key
    function displayName(ind) { return (ind && ind.display_name) || (ind && ind.name) || ''; }

    // ============================================================
    // 最新价标签（TV 式：越界吸附到价格轴顶/底）
    // ============================================================
    function updateLastPriceLabel() {
        const container = document.getElementById('main-chart');
        const chart = state.charts.main, candle = state.series.candle;
        let lab = state.lastPriceEl;
        if (!chart || !candle || !state.ohlcv || !state.ohlcv.length) {
            if (lab) lab.style.display = 'none';
            return;
        }
        if (!lab || !lab.isConnected) {
            lab = document.createElement('div');
            lab.className = 'last-price-label';
            container.appendChild(lab);
            state.lastPriceEl = lab;
        }
        const last = state.ohlcv[state.ohlcv.length - 1];
        const prev = state.ohlcv[state.ohlcv.length - 2] || last;
        const up = last.close >= prev.close;
        const y = candle.priceToCoordinate(last.close);
        if (y == null) { lab.style.display = 'none'; return; }
        //  pane 高度直接量容器（勿用 querySelector('div')：标签自身可能成为首个 div
        //  导致 paneH 恒=50、标签被 ▼ 吸附钳死直到刷新）
        const paneH = Math.max(50, container.clientHeight - 30);
        let yy = y, arrow = '';
        if (y < 0) { yy = 4; arrow = '▲ '; }          // 最新价高于可视区 → 吸附顶部
        else if (y > paneH) { yy = paneH - 4; arrow = '▼ '; }  // 低于可视区 → 吸附底部
        lab.style.display = 'block';
        lab.style.top = `${yy}px`;
        lab.style.background = up ? 'var(--up)' : 'var(--down)';
        lab.textContent = arrow + last.close.toFixed(2);
    }

    // ============================================================
    // 指标显隐切换（交易面板式）
    // ============================================================
    function getIndicatorColor(ind) {
        if (ind.style && ind.style.color) return ind.style.color;
        if (ind.lines && ind.lines.length > 0 && ind.lines[0].style && ind.lines[0].style.color) {
            return ind.lines[0].style.color;
        }
        return '#4fc3f7';
    }

    function updateDataInfo() {
        // 左上统计（bars | indicators）：init/全渲染/增量更新统一走这里，保证实时
        document.getElementById('data-info').textContent =
            `${state.ohlcv.length} bars | ${Object.keys(state.indicators).length} indicators`;
    }

    function renderIndicatorBar() {
        const bar = document.getElementById('indicator-bar');
        bar.innerHTML = '<span class="label">指标:</span>';

        const names = Object.keys(state.indicators);
        if (names.length === 0) {
            const empty = document.createElement('span');
            empty.style.cssText = 'font-size:11px;color:#555;';
            empty.textContent = '（暂无指标）';
            bar.appendChild(empty);
            return;
        }

        names.forEach(name => {
            const ind = state.indicators[name];
            const visible = state.visibility[name] !== false;
            const chip = document.createElement('div');
            chip.className = `ind-chip ${visible ? '' : 'hidden'}`;
            chip.title = '点击切换显示/隐藏';

            const dot = document.createElement('span');
            dot.className = 'dot';
            dot.style.background = getIndicatorColor(ind);
            chip.appendChild(dot);

            const txt = document.createElement('span');
            txt.className = 'name';
            let label = displayName(ind);
            if (ind.subplot) label += ' [副图]';
            if (ind.scope === 'timeframe') label += ' [本周期]';
            txt.textContent = label;
            chip.appendChild(txt);

            const eye = document.createElement('span');
            eye.className = 'eye';
            eye.textContent = visible ? '👁' : '🚫';
            chip.appendChild(eye);

            // 设置按钮（⚙），不触发显隐
            const gear = document.createElement('span');
            gear.className = 'gear';
            gear.textContent = '⚙';
            gear.title = '设置参数/样式';
            gear.onclick = (e) => { e.stopPropagation(); openSettings(name); };
            chip.appendChild(gear);

            chip.onclick = () => toggleIndicator(name);
            // 右键菜单：设置 / 删除
            chip.oncontextmenu = (e) => {
                e.preventDefault(); e.stopPropagation();
                showContextMenu(e.clientX, e.clientY, [
                    { label: '设置参数/样式', onClick: () => openSettings(name) },
                    { label: '删除指标', danger: true, onClick: () => deleteIndicator(name) },
                ]);
            };
            bar.appendChild(chip);
        });
    }

    function toggleIndicator(name) {
        const nowVisible = state.visibility[name] === false; // 当前隐藏 → 切到显示
        state.visibility[name] = nowVisible;

        // 应用到该指标的所有 series
        (state.seriesMap[name] || []).forEach(series => {
            try { series.applyOptions({ visible: nowVisible }); } catch (e) {}
        });

        // 副图指标：全隐藏则折叠副图，任一显示则展开
        updateSubplotVisibility();

        renderIndicatorBar();
        log('info', `指标 ${name} ${nowVisible ? '显示' : '隐藏'}`);
    }

    function deleteIndicator(name) {
        const url = `/api/indicator/${encodeURIComponent(name)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`;
        fetch(url, { method: 'DELETE' })
            .then(r => r.json())
            .then(d => { if (d.error) log('error', `删除指标失败: ${d.error}`); });
    }

    // ============================================================
    // 图表渲染
    // ============================================================
    let renderScheduled = false;

    function renderChart() {
        // 使用 requestAnimationFrame 确保 DOM 已布局
        if (renderScheduled) return;
        renderScheduled = true;
        requestAnimationFrame(() => {
            renderScheduled = false;
            _doRenderChart();
        });
    }

    function _doRenderChart() {
        try {
            _renderChartInner();
        } catch (e) {
            log('error', `图表渲染错误: ${e.message}`);
            console.error(e);
        }
    }

    function _renderChartInner() {
        const container = document.getElementById('main-chart');
        const emptyState = document.getElementById('empty-state');

        // 全白户引导页：无板 = 搜索流建现场（用户侧无空板）
        const guide = document.getElementById('guide');
        if (!state.boards || state.boards.length === 0) {
            guide.style.display = 'block';
            emptyState.style.display = 'none';
            container.innerHTML = '';
            clearSubplots();
            renderIndicatorBar();
            updateDataInfo();
            return;
        }
        guide.style.display = 'none';

        if (!state.ohlcv || state.ohlcv.length === 0) {
            emptyState.style.display = 'block';
            container.innerHTML = '';
            clearSubplots();  // 无数据时也要清空副图，避免残留
            renderIndicatorBar();  // 无数据时也要刷新指标栏，避免残留旧chip
            updateDataInfo();  // 刷新统计，避免残留旧值
            return;
        }
        emptyState.style.display = 'none';

        // 销毁旧图表
        Object.values(state.charts).forEach(c => {
            try { c.remove(); } catch(e) {}
        });
        state.charts = {};
        state.series = {};
        state.seriesMap = {};
        state.drawingHandles = {};  // 重建图表时清空划线句柄
        state.subplotSeries = {};
        state.timeIndex = new Map(state.ohlcv.map((bar, i) => [Math.floor(bar.timestamp / 1000), i]));

        // 确保容器有尺寸
        const width = container.clientWidth || container.offsetWidth || 800;
        const height = container.clientHeight || container.offsetHeight || 500;

        // 是否日内周期（决定时间显示格式）
        const intraday = isIntraday(state.currentTimeframe);

        // 创建主图
        _charts.length = 0;   // 主图重建 = 旧图销毁，注册表重置
        const chart = _registerChart(LightweightCharts.createChart(container, {
            width: width,
            height: height,
            layout: {
                background: { type: 'solid', color: '#131722' },
                textColor: '#d1d4dc',
                attributionLogo: false,  // 隐藏 TradingView 署名 logo
            },
            grid: {
                vertLines: { color: '#1e222d' },
                horzLines: { color: '#1e222d' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            // 价格轴禁用拖动缩放（防自动缩放失效）；双击价格轴可恢复自动缩放
            handleScale: {
                axisPressedMouseMove: { time: true, price: false },
                axisDoubleClickReset: { time: true, price: true },
            },
            localization: {
                timeFormatter: (t) => formatTimeCN(t, intraday),
            },
            // 固定右轴最小宽度，保证主图与副图绘图区横向对齐
            rightPriceScale: { minimumWidth: 80 },
            // 预留左轴宽度（不显示），与副图左轴预留一致，保证横向对齐
            leftPriceScale: { visible: false, minimumWidth: 60 },
            timeScale: {
                timeVisible: intraday,
                secondsVisible: false,
                tickMarkFormatter: (time) => formatTimeCN(time, intraday),
            },
        }), container);
        state.charts.main = chart;

        // 历史回溯只由真实用户手势触发：程序化渲染重置，手势置位（一次性绑定防叠加）
        state._userTouched = false;
        if (!container._akGestureBound) {
            container._akGestureBound = true;
            ['wheel', 'pointerdown', 'touchstart'].forEach(ev =>
                container.addEventListener(ev, () => { state._userTouched = true; }, { passive: true }));
        }

        // 向左平移到接近最左 → 按需加载更早历史
        // （程序化设置视口不触发，只有用户手动操作才触发）
        chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
            reportView();  // 视口变化即上报（节流）
            updateLastPriceLabel();  // 滚动/缩放时刷新最新价标签吸附
            if (state._programmaticRange) { state._programmaticRange = false; return; }
            if (!state._userTouched) return;  // 非用户手势（init/刷新/切板等程序化渲染）不补历史
            if (range && range.from <= 2) {
                loadMoreHistory();
            }
        });

        // K线 (v5 API: addSeries)
        const candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
            upColor: '#26a69a',
            downColor: '#ef5350',
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
            borderVisible: false,
            lastValueVisible: false,   // 关掉内建标签，用自绘可吸附标签
            priceLineVisible: true,    // 保留最新价水平线
        });

        const candleData = buildCandleData();
        // 首渲染的 range 事件属程序化行为：置防误载标志，
        // 修复新客户端 init/刷新时 setData 触发的 range 事件被误判为用户左滚而静默补一次历史
        state._programmaticRange = true;
        candleSeries.setData(candleData);
        state.series.candle = candleSeries;

        // Markers on candlestick (v5 API: createSeriesMarkers)
        if (state.markers && state.markers.length > 0) {
            // 越界过滤：范围外标记不送进 LWC（否则吸附首/末根画错位置），与后端校验双保险
            const lo = candleData.length ? candleData[0].time : -Infinity;
            const hi = candleData.length ? candleData[candleData.length - 1].time : Infinity;
            const markers = state.markers.map(m => ({
                ...m,
                // 单位自适应：<1e11 视为秒→转毫秒，再统一 /1000 给 LWC(秒)
                time: Math.floor((m.time < 1e11 ? m.time * 1000 : m.time) / 1000)
            })).filter(m => m.time >= lo && m.time <= hi)
              .sort((a, b) => a.time - b.time);
            LightweightCharts.createSeriesMarkers(candleSeries, markers);
        }

        // 划线（作为图表 series/priceLine，可被 takeScreenshot 截到）
        syncDrawings();

        // 主图指标
        renderMainIndicators(chart);

        // 副图
        renderSubplots();

        // 主副图时间轴联动
        syncTimeScales();

        // 初始强制同步：副图视口 = 主图视口，保证横向对齐
        const initRange = chart.timeScale().getVisibleLogicalRange();
        Object.entries(state.charts).forEach(([key, other]) => {
            if (key !== 'main' && initRange) {
                other.timeScale().setVisibleLogicalRange(initRange);
            }
        });

        // 主副图十字光标联动
        setupCrosshairSync();

        // 上报当前视图
        reportView();

        // 默认只显示最新200根（右对齐），不全量显示
        showLatest(200);

        // 记录当前K线数（供原地更新判断跟随）
        state._prevTotal = state.ohlcv.length;

        // 更新数据信息
        updateDataInfo();

        // 挂载已画好线的交互（双击选中/拖动/端点/右键菜单）
        attachDrawingInteraction();
        updateLastPriceLabel();
        // 自动缩放稳定后复核一次，避免取值过早导致标签错位
        requestAnimationFrame(() => updateLastPriceLabel());

        // 渲染指标显隐栏
        renderIndicatorBar();

        // resize 监听
        const resizeObserver = new ResizeObserver(() => {
            chart.applyOptions({
                width: container.clientWidth,
                height: container.clientHeight,
            });
        });
        resizeObserver.observe(container);
    }

    // 记录指标的 series 并应用当前显隐状态
    function trackSeries(name, series) {
        if (!state.seriesMap[name]) state.seriesMap[name] = [];
        state.seriesMap[name].push(series);
        const visible = state.visibility[name] !== false;
        series.applyOptions({ visible });
    }

    // 构建 K线数据
    function buildCandleData() {
        return state.ohlcv.map(bar => ({
            time: Math.floor(bar.timestamp / 1000),
            open: bar.open, high: bar.high, low: bar.low, close: bar.close,
        }));
    }

    // 构建指标线数据。null 用"空白点"(仅time)占位，保留时间槽，保证主副图时间轴对齐
    function buildSeriesData(values, type, style) {
        return values.map((v, i) => {
            const time = Math.floor(state.ohlcv[i]?.timestamp / 1000) || i;
            if (v === null || v === undefined) {
                return { time };  // whitespace 数据点：占位但不画值
            }
            const point = { time, value: v };
            if (type === 'histogram' || type === 'bar') {
                // 默认涨跌自动红绿；style.autoColor===false 时用系列固定色
                if (!(style && style.autoColor === false)) {
                    point.color = v >= 0 ? '#26a69a' : '#ef5350';
                }
            }
            return point;
        });
    }

    // ============================================================
    // 实时数据原地更新（不重建图表，保持缩放/平移，跟随右缘）
    // shift>0 表示历史前插了 shift 根，视口需右移 shift 保持看到原K线
    // ============================================================
    function applyDataUpdate(shift = 0) {
        // 结构未就绪 → 全量渲染
        if (!state.charts.main || !state.series.candle || !state.ohlcv.length) {
            renderChart();
            return;
        }
        const main = state.charts.main;
        const ts = main.timeScale();
        const prevRange = ts.getVisibleLogicalRange();
        const prevTotal = state._prevTotal || state.ohlcv.length;

        // 更新K线
        state.series.candle.setData(buildCandleData());

        // 更新常驻成交量窗格
        if (state.volumeSeries) {
            state.volumeSeries.setData(state.ohlcv.map(b => ({
                time: Math.floor(b.timestamp / 1000), value: b.volume,
                color: b.close >= b.open ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
            })));
        }

        // 更新所有指标 series（主图+副图）
        Object.entries(state.indicators).forEach(([name, ind]) => {
            const seriesList = state.seriesMap[name] || [];
            if (ind.lines && ind.lines.length) {
                zOrdered(ind.lines).forEach((line, idx) => {
                    const s = seriesList[idx];
                    if (s && line.values) s.setData(buildSeriesData(line.values, line.type || 'line', line.style));
                });
            } else if (ind.values && seriesList[0]) {
                seriesList[0].setData(buildSeriesData(ind.values, ind.type || 'line', ind.style));
            }
        });

        // 恢复视口（bug2 根治）：仅在前插(shift>0)或追加(newTotal>prevTotal)时动视口；
        // 原地 tick 更新（total 不变）绝不碰视口——否则 wasAtRight 分支的 +2 右边距
        // 会被计入下一次的 width，每 tick 蠕变 +2 格（"价格一变就往右缩一小格"）
        const newTotal = state.ohlcv.length;
        if (prevRange && (shift > 0 || newTotal > prevTotal)) {
            state._programmaticRange = true;  // 程序化恢复，不触发历史加载
            if (shift > 0) {
                // 历史前插：视口右移 shift，保持看到原来的K线
                ts.setVisibleLogicalRange({ from: prevRange.from + shift, to: prevRange.to + shift });
            } else {
                const wasAtRight = prevRange.to >= prevTotal - 1;
                if (wasAtRight) {
                    // 右缘跟随新K线：宽度严格守恒（右边距只加一次，不累积）
                    const width = prevRange.to - prevRange.from;
                    ts.setVisibleLogicalRange({ from: newTotal + 2 - width, to: newTotal + 2 });
                } else {
                    ts.setVisibleLogicalRange(prevRange);
                }
            }
        }
        state._prevTotal = newTotal;
        updateDataInfo();  // 增量路径（轮询新bar/回溯前插）也要实时刷新统计
        reportView();
        updateLegends(null);
        updateLastPriceLabel();
        requestAnimationFrame(() => updateLastPriceLabel());
    }

    // ============================================================
    // 视口控制（程序化设置不触发历史加载）
    // ============================================================
    function setRangeProgrammatic(range) {
        state._programmaticRange = true;
        state.charts.main.timeScale().setVisibleLogicalRange(range);
    }

    // 默认只显示最新 N 根（右对齐），而非全量
    function showLatest(n = 200) {
        if (!state.charts.main || !state.ohlcv.length) return;
        const total = state.ohlcv.length;
        setRangeProgrammatic({ from: Math.max(0, total - n), to: total + 2 });
    }

    // ============================================================
    // 视图上报（把用户当前看哪告诉后端，供 agent 查询）
    // ============================================================
    let viewReportTimer = null;

    function reportView() {
        clearTimeout(viewReportTimer);
        viewReportTimer = setTimeout(() => {
            if (!state.charts.main || !state.ohlcv.length) return;
            const lr = state.charts.main.timeScale().getVisibleLogicalRange();
            if (!lr) return;
            const n = state.ohlcv.length;
            const fromIdx = Math.max(0, Math.floor(lr.from));
            const toIdx = Math.min(n - 1, Math.ceil(lr.to));
            const fromTime = state.ohlcv[fromIdx] ? state.ohlcv[fromIdx].timestamp : null;
            const toTime = state.ohlcv[toIdx] ? state.ohlcv[toIdx].timestamp : null;
            fetch('/api/view', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    board_id: state.currentBoard,
                    timeframe: state.currentTimeframe,
                    from_time: fromTime, to_time: toTime,
                    bars: toIdx - fromIdx + 1
                })
            }).catch(() => {});
        }, 500);
    }

    // ============================================================
    // 历史K线按需加载（向左平移触发）
    // ============================================================
    let historyLoading = false;

    async function loadMoreHistory() {
        if (historyLoading) return;
        if (!state.currentBoard || !state.currentTimeframe) return;
        historyLoading = true;
        try {
            const r = await fetch(
                `/api/board/${state.currentBoard}/timeframe/${state.currentTimeframe}/backfill`,
                { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: 200 }) }
            );
            const d = await r.json();
            if (d.prepended > 0) log('info', `📜 加载历史 +${d.prepended} 根`);
        } catch (e) {
            log('error', `加载历史失败: ${e.message}`);
        } finally {
            historyLoading = false;
        }
    }

    function renderMainIndicators(chart) {
        Object.entries(state.indicators).forEach(([name, ind]) => {
            if (ind.subplot) return; // 副图指标不在主图画

            // 多线模式
            if (ind.lines && ind.lines.length > 0) {
                zOrdered(ind.lines).forEach((line, idx) => {
                    const series = createSeries(chart, line.type || 'line', `${name}_${idx}`, line.style);
                    if (series) trackSeries(name, series);
                    if (series && line.values) {
                        series.setData(buildSeriesData(line.values, line.type || 'line', line.style));

                        if (line.markers && line.markers.length > 0) {
                            const markers = line.markers.map(m => ({
                                ...m,
                                time: Math.floor(m.time / 1000)
                            })).sort((a, b) => a.time - b.time);
                            LightweightCharts.createSeriesMarkers(series, markers);
                        }
                    }
                });
                return;
            }

            // 单线模式
            const type = ind.type || 'line';
            const series = createSeries(chart, type, name, ind.style);
            if (series) trackSeries(name, series);
            if (series && ind.values) {
                series.setData(buildSeriesData(ind.values, type, ind.style));

                if (ind.markers && ind.markers.length > 0) {
                    const markers = ind.markers.map(m => ({
                        ...m,
                        time: Math.floor(m.time / 1000)
                    })).sort((a, b) => a.time - b.time);
                    LightweightCharts.createSeriesMarkers(series, markers);
                }
            }
        });
    }

    // 绘制层级=创建顺序：柱状先创建（垫底），线/面积后创建（在上），组内保持原序。
    // 创建与 setData 必须用同一排序，保证 seriesMap 索引对齐。
    function zOrdered(lines) {
        const rank = (l) => (l.type === 'histogram' || l.type === 'bar') ? 0 : 1;
        return [...lines].sort((a, b) => rank(a) - rank(b));
    }

    function createSeries(chart, type, name, style) {
        style = style || {};
        const opts = {
            color: style.color || '#4fc3f7',
            lineWidth: style.lineWidth || 2,
            priceScaleId: style.priceScaleId || 'right',
            // 指标默认不显示最后值标记和价格辅助线（减少视觉干扰）
            priceLineVisible: false,
            lastValueVisible: false,
            // 十字光标时也不显示指标的价格标签
            crosshairMarkerVisible: false,
        };
        // 线型（0实线/1点线/2虚线）
        if (style.lineStyle !== undefined) {
            opts.lineStyle = style.lineStyle;
        }

        // lineType
        if (style.lineType !== undefined) {
            opts.lineType = style.lineType;
        }

        let series;
        switch (type) {
            case 'line':
                series = chart.addSeries(LightweightCharts.LineSeries, opts);
                break;
            case 'area':
                series = chart.addSeries(LightweightCharts.AreaSeries, {
                    ...opts,
                    topColor: style.topColor || opts.color + '80',
                    bottomColor: style.bottomColor || opts.color + '00',
                    lineColor: style.color || opts.color,
                });
                break;
            case 'baseline':
                series = chart.addSeries(LightweightCharts.BaselineSeries, {
                    ...opts,
                    baseValue: style.baseValue || { type: 'price', price: 0 },
                    topFillColor1: style.topFillColor1 || '#26a69a40',
                    topFillColor2: style.topFillColor2 || '#26a69a10',
                    topLineColor: style.topLineColor || '#26a69a',
                    bottomFillColor1: style.bottomFillColor1 || '#ef535010',
                    bottomFillColor2: style.bottomFillColor2 || '#ef535040',
                    bottomLineColor: style.bottomLineColor || '#ef5350',
                });
                break;
            case 'histogram':
            case 'bar':
                series = chart.addSeries(LightweightCharts.HistogramSeries, {
                    ...opts,
                    color: style.color || '#4fc3f7',
                    priceScaleId: style.priceScaleId || 'right',
                });
                break;
            default:
                series = chart.addSeries(LightweightCharts.LineSeries, opts);
        }
        return series;
    }

    // ============================================================
    // 主副图时间轴联动（缩放/滚动同步）
    // ============================================================
    let isSyncing = false;

    function clearSubplots() {
        // 销毁所有副图图表实例并清空 DOM
        Object.keys(state.charts).forEach(key => {
            if (key.startsWith('subplot_')) {
                try { state.charts[key].remove(); } catch (e) {}
                delete state.charts[key];
            }
        });
        const container = document.getElementById('subplots');
        if (container) container.innerHTML = '';
    }

    // ============================================================
    // 主副图十字光标联动
    // ============================================================
    function primarySeriesFor(key) {
        if (key === 'main') return state.series.candle;
        if (key === 'volume') return state.volumeSeries;
        const name = key.replace('subplot_', '');
        for (const [indName, ind] of Object.entries(state.indicators)) {
            if (ind.subplot === name && state.seriesMap[indName] && state.seriesMap[indName][0]) {
                return state.seriesMap[indName][0];
            }
        }
        return null;
    }

    function valueAtTime(key, time) {
        if (!state.timeIndex) return null;
        const i = state.timeIndex.get(time);
        if (i === undefined) return null;
        if (key === 'main') return state.ohlcv[i] ? state.ohlcv[i].close : null;
        if (key === 'volume') return state.ohlcv[i] ? state.ohlcv[i].volume : null;
        const name = key.replace('subplot_', '');
        for (const [indName, ind] of Object.entries(state.indicators)) {
            if (ind.subplot !== name) continue;
            if (ind.lines && ind.lines.length) return ind.lines[0].values[i];
            if (ind.values) return ind.values[i];
        }
        return null;
    }

    // ============ 图例（OHLC + 指标读数，随十字标更新，移开显示最新） ============
    function fmtP(v) { return (v == null || !isFinite(v)) ? '--' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    function fmtC(v) { if (v == null || !isFinite(v)) return '--'; const a = Math.abs(v);
        if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿'; if (a >= 1e4) return (v / 1e4).toFixed(2) + '万';
        return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }); }

    // v0.4 优化点1 补漏：图例符号位用统一显示名（源名: 标的名），不露裸板 id
    function boardLabel() {
        const bd = (state.boards || []).find(b => b.id === state.currentBoard);
        return (bd && (bd.name || bd.identity_display)) || state.currentBoard || '';
    }

    function legendIndex(timeSec) {
        if (timeSec != null && state.timeIndex) { const i = state.timeIndex.get(timeSec); if (i !== undefined) return i; }
        return state.ohlcv.length - 1;
    }

    function ensureLegendEl(key, host, sub) {
        if (!host) return null;
        state.legendEls = state.legendEls || {};
        let el = state.legendEls[key];
        if (!el || !el.isConnected) {
            el = document.createElement('div');
            el.className = 'legend' + (sub ? ' sub' : '');
            host.appendChild(el);
            state.legendEls[key] = el;
        }
        return el;
    }

    function indLegendHtml(ind, i) {
        const dot = (c) => `<span class="dot" style="background:${c}"></span>`;
        if (ind.lines && ind.lines.length) {
            return ind.lines.map(l => {
                const c = (l.style && l.style.color) || '#4fc3f7';
                return `<span class="lg">${dot(c)}${l.name} <b>${fmtP(l.values ? l.values[i] : null)}</b></span>`;
            }).join('');
        }
        const c = (ind.style && ind.style.color) || '#4fc3f7';
        return `<span class="lg">${dot(c)}${displayName(ind)} <b>${fmtP(ind.values ? ind.values[i] : null)}</b></span>`;
    }

    // 图例按"一个指标一行"纵向排布；行数超过 maxRows 时回退横排（.inline）
    function setLegend(key, host, sub, rows, maxRows) {
        const el = ensureLegendEl(key, host, sub);
        if (!el) return;
        el.classList.toggle('inline', rows.length > maxRows);
        el.innerHTML = rows.map(r => `<div class="row">${r}</div>`).join('');
    }

    function updateLegends(timeSec) {
        const i = legendIndex(timeSec);
        const b = state.ohlcv[i];
        // 主图：第1行 OHLC+涨跌，其后每个叠加指标各占一行
        const mainRows = [];
        if (b) {
            const prev = state.ohlcv[i - 1] || b;
            const chg = prev.close ? (b.close - prev.close) / prev.close * 100 : 0;
            const cls = b.close >= b.open ? 'up' : 'down';
            mainRows.push(`<span class="sym">${boardLabel()} · ${state.currentTimeframe || ''}</span>`
                + `<span>O <b>${fmtP(b.open)}</b></span><span>H <b>${fmtP(b.high)}</b></span>`
                + `<span>L <b>${fmtP(b.low)}</b></span><span>C <b class="${cls}">${fmtP(b.close)}</b></span>`
                + `<span class="${chg >= 0 ? 'up' : 'down'}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>`);
            Object.values(state.indicators).forEach(ind => { if (!ind.subplot) mainRows.push(indLegendHtml(ind, i)); });
        }
        setLegend('main', document.getElementById('main-chart'), false, mainRows, 6);
        // 成交量：单行
        setLegend('volume', state.volDiv, true,
            b ? [`<span class="lg">VOL <b class="${b.close >= b.open ? 'up' : 'down'}">${fmtC(b.volume)}</b></span>`] : [], 1);
        // 各副图：每个指标一行
        Object.keys(state.subplots).forEach(name => {
            const rows = [];
            Object.values(state.indicators).forEach(ind => { if (ind.subplot === name) rows.push(indLegendHtml(ind, i)); });
            setLegend('subplot_' + name, state.subplotDivs[name], true, rows, 2);
        });
    }

    function setupCrosshairSync() {
        Object.entries(state.charts).forEach(([key, chart]) => {
            // bug4：价格更新后 setData 会让 LWC 对"带程序化十字准星的图"重发 crosshairMove，
            // 同步链会把它当源反向传播，把用户悬停图的水平线 setCrosshairPosition 吸附到K线值。
            // 用真实鼠标在哪个图上（mousemove/mouseleave）判定唯一同步源，程序化重发一律忽略。
            const el = key === 'main' ? document.getElementById('main-chart') : state.subplotDivs[key];
            if (el && !el._akHoverBound) {
                el._akHoverBound = true;
                el.addEventListener('mousemove', () => { state._hoverChartKey = key; }, { passive: true });
                el.addEventListener('mouseleave', () => {
                    if (state._hoverChartKey === key) state._hoverChartKey = null;
                }, { passive: true });
            }
            chart.subscribeCrosshairMove(param => {
                if (state._crosshairSyncing) return;
                const isUserHover = state._hoverChartKey === key;
                if (!isUserHover && param.point) return;  // 程序化重发：不传播（离开清除仍放行）
                state._crosshairSyncing = true;
                updateLegends(param.time === undefined ? null : param.time);
                try {
                    Object.entries(state.charts).forEach(([otherKey, other]) => {
                        if (other === chart) return;
                        if (param.time === undefined || !param.point) {
                            other.clearCrosshairPosition();
                            return;
                        }
                        const series = primarySeriesFor(otherKey);
                        const val = valueAtTime(otherKey, param.time);
                        if (series && val !== null && val !== undefined) {
                            other.setCrosshairPosition(val, param.time, series);
                        }
                    });
                } finally {
                    state._crosshairSyncing = false;
                }
            });
        });
    }

    // ============================================================
    // 划线渲染（作为图表原生对象，可被 takeScreenshot 截到）
    //   hline  -> createPriceLine（全宽水平线+轴标签）
    //   trend  -> 两点 LineSeries（直线段）
    // ============================================================
    function lineStyleEnum(s) {
        return s === 'dashed' ? 2 : s === 'dotted' ? 1 : 0;
    }

    function removeDrawingHandle(id) {
        const h = (state.drawingHandles || {})[id];
        if (!h) return;
        try {
            if (h.kind === 'priceline') state.series.candle && state.series.candle.removePriceLine(h.obj);
            else state.charts.main && state.charts.main.removeSeries(h.obj);
        } catch (e) {}
        delete state.drawingHandles[id];
    }

    function syncDrawings() {
        const chart = state.charts.main, candle = state.series.candle;
        if (!chart || !candle) return;
        state.drawingHandles = state.drawingHandles || {};

        // 删除已不存在的划线
        Object.keys(state.drawingHandles).forEach(id => {
            if (!state.drawings[id]) removeDrawingHandle(id);
        });

        Object.values(state.drawings).forEach(d => {
            const visible = d.visible !== false;
            if (!visible) { removeDrawingHandle(d.id); return; }

            if (d.type === 'hline') {
                removeDrawingHandle(d.id);  // priceLine 不支持原地改，重建
                const pl = candle.createPriceLine({
                    price: d.points[0].price,
                    color: d.color || '#ef5350',
                    lineWidth: d.lineWidth || 2,
                    lineStyle: lineStyleEnum(d.lineStyle),
                    axisLabelVisible: true,
                    title: d.text || ''
                });
                state.drawingHandles[d.id] = { kind: 'priceline', obj: pl };
            } else {
                removeDrawingHandle(d.id);
                const s = chart.addSeries(LightweightCharts.LineSeries, {
                    color: d.color || '#ef5350',
                    lineWidth: d.lineWidth || 2,
                    lineStyle: lineStyleEnum(d.lineStyle),
                    crosshairMarkerVisible: false,
                    lastValueVisible: false,
                    priceLineVisible: false,
                    priceScaleId: 'right'
                });
                s.setData((d.points || []).map(p => ({
                    time: Math.floor(p.time / 1000), value: p.price
                })));
                state.drawingHandles[d.id] = { kind: 'series', obj: s };
            }
        });
    }

    function syncTimeScales() {
        const charts = Object.values(state.charts);
        charts.forEach(chart => {
            chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (isSyncing || !range) return;
                isSyncing = true;
                charts.forEach(other => {
                    if (other !== chart) {
                        other.timeScale().setVisibleLogicalRange(range);
                    }
                });
                isSyncing = false;
            });
        });
    }

    function renderSubplots() {
        const container = document.getElementById('subplots');
        container.innerHTML = '';
        state.subplotDivs = {};

        // 先销毁旧的副图图表实例（避免切换周期后残留）
        Object.keys(state.charts).forEach(key => {
            if (key.startsWith('subplot_') || key === 'volume') {
                try { state.charts[key].remove(); } catch (e) {}
                delete state.charts[key];
            }
        });

        // ---- 常驻成交量窗格（不可删除/折叠，始终位于副图最上） ----
        const volDiv = document.createElement('div');
        volDiv.className = 'subplot';
        volDiv.style.height = '110px';
        volDiv.innerHTML = `<div class="subplot-title">成交量 VOL</div>`;
        container.appendChild(volDiv);
        state.volDiv = volDiv;
        const intradayV = isIntraday(state.currentTimeframe);
        const volChart = _registerChart(LightweightCharts.createChart(volDiv, {
            width: volDiv.clientWidth, height: 90,
            layout: { background: { type: 'solid', color: '#131722' }, textColor: '#d1d4dc', attributionLogo: false },
            grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
            handleScale: {
                axisPressedMouseMove: { time: true, price: false },
                axisDoubleClickReset: { time: true, price: true },
            },
            localization: { timeFormatter: (t) => formatTimeCN(t, intradayV) },
            rightPriceScale: { minimumWidth: 80 },
            leftPriceScale: { visible: false, minimumWidth: 60 },
            timeScale: { visible: false },
        }), volDiv);
        state.charts['volume'] = volChart;
        state.volumeSeries = volChart.addSeries(LightweightCharts.HistogramSeries, {
            priceScaleId: 'right',
            priceFormat: { type: 'volume' },
            lastValueVisible: false,
            priceLineVisible: false,
        });
        state.volumeSeries.setData(state.ohlcv.map(b => ({
            time: Math.floor(b.timestamp / 1000), value: b.volume,
            color: b.close >= b.open ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
        })));
        // 成交量窗格跟随容器宽度变化，保证与主图 barSpacing 一致（防错位）
        new ResizeObserver(() => {
            volChart.applyOptions({ width: volDiv.clientWidth, height: 90 });
        }).observe(volDiv);

        Object.entries(state.subplots).forEach(([name, sp]) => {
            const div = document.createElement('div');
            div.className = 'subplot';
            div.style.height = `${sp.height || 150}px`;
            div.innerHTML = `<div class="subplot-title">${sp.title || name}</div>`;
            container.appendChild(div);
            state.subplotDivs[name] = div;

            // 创建副图图表
            const intraday = isIntraday(state.currentTimeframe);
            const chart = _registerChart(LightweightCharts.createChart(div, {
                width: div.clientWidth,
                height: (sp.height || 150) - 20,
                layout: {
                    background: { type: 'solid', color: '#131722' },
                    textColor: '#d1d4dc',
                    attributionLogo: false,  // 隐藏 TradingView 署名 logo
                },
                grid: {
                    vertLines: { color: '#1e222d' },
                    horzLines: { color: '#1e222d' },
                },
                handleScale: {
                    axisPressedMouseMove: { time: true, price: false },
                    axisDoubleClickReset: { time: true, price: true },
                },
                localization: {
                    timeFormatter: (t) => formatTimeCN(t, intraday),
                },
                // 与主图相同的右轴最小宽度，保证对齐
                rightPriceScale: { minimumWidth: 80 },
                // 预留与主图相同的左轴宽度（不显示），保证横向对齐
                leftPriceScale: { visible: false, minimumWidth: 60 },
                timeScale: { visible: false },
            }), div);
            state.charts[`subplot_${name}`] = chart;
            // 副图跟随容器宽度变化，保证与主图 barSpacing 一致（防错位）
            new ResizeObserver(() => {
                chart.applyOptions({ width: div.clientWidth, height: (sp.height || 150) - 20 });
            }).observe(div);

            // 画该副图上的指标
            Object.entries(state.indicators).forEach(([indName, ind]) => {
                if (ind.subplot !== name) return;

                if (ind.lines && ind.lines.length > 0) {
                    zOrdered(ind.lines).forEach((line, idx) => {
                        const series = createSeries(chart, line.type || 'line', `${indName}_${idx}`, line.style);
                        if (series) trackSeries(indName, series);
                        if (series && line.values) {
                            series.setData(buildSeriesData(line.values, line.type || 'line', line.style));
                        }
                    });
                } else {
                    const series = createSeries(chart, ind.type || 'line', indName, ind.style);
                    if (series) trackSeries(indName, series);
                    if (series && ind.values) {
                        series.setData(buildSeriesData(ind.values, ind.type || 'line', ind.style));
                    }
                }
            });
        });

        // 应用副图折叠（全隐藏则收起）
        updateSubplotVisibility();
        updateLegends(null);
    }

    // 判断某副图是否还有可见指标
    function subplotHasVisibleIndicator(subplotName) {
        return Object.entries(state.indicators).some(([indName, ind]) =>
            ind.subplot === subplotName && state.visibility[indName] !== false
        );
    }

    // 副图所有指标都隐藏 → 折叠释放空间；任一恢复 → 展开
    function updateSubplotVisibility() {
        Object.keys(state.subplots).forEach(name => {
            const div = state.subplotDivs[name];
            if (!div) return;
            const hasVisible = subplotHasVisibleIndicator(name);
            div.style.display = hasVisible ? '' : 'none';
        });
    }

    // ============================================================
    // 截图（收到 WS snapshot_request 时合成主图+成交量+副图并上传）
    // ============================================================
    function captureSnapshot() {
        const items = [];
        if (state.charts.main) items.push({ key: 'main', chart: state.charts.main });
        if (state.charts.volume) items.push({ key: 'volume', chart: state.charts.volume });
        Object.keys(state.charts).forEach(k => { if (k.startsWith('subplot_')) items.push({ key: k, chart: state.charts[k] }); });
        if (!items.length) return;
        const shots = items.map(it => { try { return it.chart.takeScreenshot(); } catch (e) { return null; } });
        const valid = shots.filter(Boolean);
        if (!valid.length) return;
        const W = Math.max(...valid.map(s => s.width));
        const H = shots.reduce((a, s) => a + (s ? s.height : 0), 0);
        const canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#131722'; ctx.fillRect(0, 0, W, H);
        let y = 0;
        items.forEach((it, idx) => {
            const s = shots[idx];
            if (!s) return;
            ctx.drawImage(s, 0, y);
            drawOverlay(ctx, it.key, y, s.height, W);
            y += s.height;
        });
        const image = canvas.toDataURL('image/png');
        fetch('/api/snapshot', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image, board_id: state.currentBoard, timeframe: state.currentTimeframe })
        }).catch(e => console.warn('snapshot upload failed', e));
    }

    // 把 DOM 覆盖层（图例/最新价标签）画进截图 canvas
    function drawOverlay(ctx, key, offY, segH, W) {
        // 图例文本
        let host = null;
        if (key === 'main') host = document.getElementById('main-chart');
        else if (key === 'volume') host = state.volDiv;
        else host = state.subplotDivs[key.replace('subplot_', '')];
        const legend = host && host.querySelector('.legend');
        if (legend) {
            ctx.font = '12px -apple-system, "Segoe UI", sans-serif';
            ctx.fillStyle = '#d1d4dc';
            ctx.textBaseline = 'top';
            legend.innerText.split('\n').forEach((line, i) => {
                if (line.trim()) ctx.fillText(line, 8, offY + 6 + i * 16);
            });
        }
        // 主图最新价标签（右轴，越界吸附）
        if (key === 'main' && state.series.candle && state.ohlcv.length) {
            const last = state.ohlcv[state.ohlcv.length - 1];
            const prev = state.ohlcv[state.ohlcv.length - 2] || last;
            const up = last.close >= prev.close;
            const y = state.series.candle.priceToCoordinate(last.close);
            if (y != null) {
                const yy = Math.max(9, Math.min(segH - 9, y));
                ctx.fillStyle = up ? '#26a69a' : '#ef5350';
                ctx.fillRect(W - 72, offY + yy - 9, 72, 18);
                ctx.fillStyle = '#fff';
                ctx.textAlign = 'center';
                ctx.fillText(last.close.toFixed(2), W - 36, offY + yy - 6);
                ctx.textAlign = 'left';
            }
        }
    }

// 程序化设置可见时间窗口（秒），并同步副图；_programmaticRange 防止误触发历史加载
function setVisibleTimeRange(fromSec, toSec) {
    const main = state.charts.main;
    if (!main || !state.ohlcv.length || !(toSec > fromSec)) return;
    try {
        state._programmaticRange = true;
        main.timeScale().setVisibleRange({ from: fromSec, to: toSec });
        const lr = main.timeScale().getVisibleLogicalRange();
        Object.entries(state.charts).forEach(([key, other]) => {
            if (key !== 'main' && lr) other.timeScale().setVisibleLogicalRange(lr);
        });
    } catch (e) {
        log('render', `setVisibleTimeRange failed: ${e && e.message ? e.message : e}`);
    }
}


    // ============================================================
    // 铭牌（Symbol Corner 只读+🔒）/ 板身份证卡 / 弹层绑定（P1 摩擦面）
    // ============================================================
    function openIdCard(boardId = null) {
        const bid = boardId || state.currentBoard;
        const lock = (state.locks || {})[bid] || {};
        const b = state.boards.find(x => x.id === bid) || {};
        const body = document.getElementById('id-card-body');
        if (!body) return;
        const stem = String(lock.script || '').split('/').pop();
        const sym = (lock.identity || {}).symbol;
        body.innerHTML = `<h3>${sym ? `${stem}: ${sym}` : (stem || bid)} · 🔒 已锁定</h3>
<pre>${JSON.stringify({ identity: lock.identity || {}, script: lock.script,
    board: bid, intervals: b.intervals || [] }, null, 2)}</pre>
<p class="hint">一标的一板：换标的/换源请「进入新现场」；分析层锚定本坐标系，不归档不克隆</p>`;
        document.getElementById('id-card').style.display = 'flex';
    }

    function bindOverlays() {
        const ic = document.getElementById('idcard-close');
        if (ic) ic.onclick = () => { document.getElementById('id-card').style.display = 'none'; };
        const ns = document.getElementById('idcard-new-scene');
        if (ns) ns.onclick = () => { document.getElementById('id-card').style.display = 'none'; openSearch(); };
        _ensureResizeObserver();
        const ba = document.getElementById('board-add');
        if (ba) ba.onclick = () => openSearch();
        const gs = document.getElementById('guide-search-btn');
        if (gs) gs.onclick = () => openSearch();
        const es = document.getElementById('empty-search-btn');
        if (es) es.onclick = () => openSearch();
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') document.getElementById('id-card').style.display = 'none';
        });
    }

    function applyQuoteTick(q) {
        // visible 行心跳：K线轮询间隙的即时最新价（标签文本+涨跌色）
        const lab = state.lastPriceEl;
        if (lab && q.price != null) {
            const prev = parseFloat(String(lab.textContent).replace(/,/g, '')) || q.price;
            lab.textContent = q.price.toLocaleString(undefined, { minimumFractionDigits: 2 });
            lab.style.background = q.price >= prev ? '#26a69a' : '#ef5350';
        }
    }

export { renderChart, applyDataUpdate, syncDrawings, renderSubplots, captureSnapshot, setVisibleTimeRange, openIdCard, bindOverlays, applyQuoteTick };
