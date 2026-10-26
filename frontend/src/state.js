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
        visibility: {},  // indicator name -> bool (default true)
        drawings: {},  // id -> SerializedDrawing（划线，属板不属周期）
        timeIndex: null,  // Map(timeSec -> ohlcv index)
        indicatorCatalog: null,  // v0.5.3：/api/indicator-catalog 缓存（指标库/设置面板共用）
        // v0.6.0 结果实例：当前板+周期的摘要/可见/选中；detail 缓存冻结结果（不可变）
        results: [],
        resultVisible: [],
        resultActive: null,
        resultDetail: {},   // result_id -> {summary, equity:{times,values}, trades:[]}
        resultMarksOn: true,
        resultSelTrade: '',   // 当前选中的交易 id（结果层描边用）
        uiTimezone: 'Asia/Shanghai',   // v0.6.0：界面时间显示时区（/api/config ui.timezone 覆盖；browser=跟随本机）
    };

// v0.4.1: 状态重置原语（自 ws.js 下沉到叶子模块，断 ws↔ui 环）
export function applyState(data) {
    state.ohlcv = data.ohlcv || [];
    state.indicators = data.indicators || {};
    // P2-fix：显隐服务端真源 → init/switch 恢复本地 visibility（刷新持久）
    Object.entries(state.indicators).forEach(([id, ind]) => { state.visibility[id] = (ind.visible !== false); });
    state.markers = data.markers || [];
    // 画线属板：服务端下发 list（id -> drawing）
    state.drawings = Array.isArray(data.drawings)
        ? Object.fromEntries(data.drawings.filter(d => d && d.id).map(d => [d.id, d]))
        : {};
    // v0.4.3 bug4：init/switch payload 的 subplots 是 list[{name,...}]，
    // 而 state.subplots 是 dict 语义（subplot_create 广播写 dict、renderSubplots 读 Object.keys）；
    // 原直赋值致 list 覆盖 dict → 任意 init/switch 后副图容器全灭（chips 仍在）
    state.subplots = Array.isArray(data.subplots)
        ? Object.fromEntries(data.subplots.map(x => [x.name, x]))
        : (data.subplots || {});
    return state;
}
