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

// v0.4.1: 状态重置原语（自 ws.js 下沉到叶子模块，断 ws↔ui 环）
export function applyState(data) {
    state.ohlcv = data.ohlcv || [];
    state.indicators = data.indicators || {};
    state.markers = data.markers || [];
    state.drawings = data.drawings || [];
    // v0.4.3 bug4：init/switch payload 的 subplots 是 list[{name,...}]，
    // 而 state.subplots 是 dict 语义（subplot_create 广播写 dict、renderSubplots 读 Object.keys）；
    // 原直赋值致 list 覆盖 dict → 任意 init/switch 后副图容器全灭（chips 仍在）
    state.subplots = Array.isArray(data.subplots)
        ? Object.fromEntries(data.subplots.map(x => [x.name, x]))
        : (data.subplots || {});
    return state;
}
