// ============================================================
// 图表原生图层偏好（v0.5.4）：按板记住 VPVR 等 layer 的显隐
// ------------------------------------------------------------
// localStorage 与指标库收藏同层：只影响本浏览器展示，不改变后端 board 状态。
// 结构：{ [board_id]: { vpvr: true, volume: false } }，按板隔离（不同标的各自决定开不开）。
// 读取失败/隐私模式：退回内存值，本次会话仍可用。
// ============================================================

const LS_KEY = 'ak.chart.layers.v1';
let _mem = null;   // localStorage 不可用时的会话兜底

function readAll() {
    if (_mem) return _mem;
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); } catch (e) { raw = null; }
    _mem = (raw && typeof raw === 'object') ? raw : {};
    return _mem;
}

function writeAll(all) {
    _mem = all;
    try { localStorage.setItem(LS_KEY, JSON.stringify(all)); } catch (e) { /* 只保留会话内 */ }
}

export function getLayerPref(boardId, layer, dflt = false) {
    if (!boardId) return dflt;
    const row = readAll()[boardId];
    // 显式 false 也要能被读到（成交量默认开，关掉后必须记住）
    return (row && Object.prototype.hasOwnProperty.call(row, layer)) ? !!row[layer] : dflt;
}

export function setLayerPref(boardId, layer, on) {
    if (!boardId) return;
    const all = readAll();
    if (!all[boardId] || typeof all[boardId] !== 'object') all[boardId] = {};
    all[boardId][layer] = !!on;
    writeAll(all);
}

export function getLayerInputs(boardId, layer) {
    if (!boardId) return null;
    const row = readAll()[boardId];
    const v = row && row[layer + 'Inputs'];
    return (v && typeof v === 'object') ? v : null;
}

export function setLayerInputs(boardId, layer, inputs) {
    if (!boardId) return;
    const all = readAll();
    if (!all[boardId] || typeof all[boardId] !== 'object') all[boardId] = {};
    if (inputs && typeof inputs === 'object' && Object.keys(inputs).length) {
        all[boardId][layer + 'Inputs'] = inputs;
    } else {
        delete all[boardId][layer + 'Inputs'];
    }
    writeAll(all);
}
