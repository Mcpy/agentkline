    // ============================================================
    // 全局状态
    // ============================================================
export const state = {
        boards: [],
        locks: {},   // board_id -> source_lock（v0.4 一标的一板）
        intervalOptions: null,  // 当前板周期选项（优化点2）
        currentBoard: null,
        currentTimeframe: null,
        ohlcv: [],
        markers: [],
        indicators: {},
        subplots: {},
        ws: null,
        charts: {},  // chart instances
        series: {},  // series instances
        seriesMap: {},  // indicator name -> [series instances]
        visibility: {},  // indicator name -> bool (default true)
        subplotDivs: {},  // subplot name -> DOM div
        subplotSeries: {},  // subplot name -> primary series
        drawings: {},  // id -> drawing (划线)
        timeIndex: null,  // Map(timeSec -> ohlcv index)
        _crosshairSyncing: false,
        _hoverChartKey: null,  // 真实鼠标悬停的图（bug4 同步源判定）
    };
