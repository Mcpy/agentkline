    // ============================================================
    // 全局状态
    // ============================================================
export const state = {
        boards: [],
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
    };
