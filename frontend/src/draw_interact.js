import { state } from './state.js';
import { log } from './log.js';
import { showContextMenu } from './menu.js';

// ============================================================
// 已画好线的交互：双击选中 / 拖动 / 端点拖动 / 右键菜单
// ============================================================
let handlesLayer = null;
let controller = null;      // 事件监听 AbortController
let drag = null;            // 当前拖拽会话

const ENDPOINT_R = 8;       // 端点命中半径
const BODY_R = 6;           // 线身命中半径

function chartEl() { return document.getElementById('main-chart'); }

// ---------- 每工具默认样式（TV：新划线继承工具默认，改样式后更新默认） ----------
const DEF_KEY = 'cb_draw_defaults';
function loadDefaults() {
    try {
        const s = JSON.parse(localStorage.getItem(DEF_KEY));
        if (s && s.hline && s.trend) return s;
    } catch (e) {}
    return {
        hline: { color: '#ef5350', lineWidth: 2, lineStyle: 'solid' },
        trend: { color: '#2962ff', lineWidth: 2, lineStyle: 'solid' },
    };
}
let drawDefaults = loadDefaults();
function persistDefaults() { try { localStorage.setItem(DEF_KEY, JSON.stringify(drawDefaults)); } catch (e) {} }

// ---------- 坐标换算 ----------
function toXY(timeSec, price) {
    const chart = state.charts.main, candle = state.series.candle;
    if (!chart || !candle) return null;
    const x = chart.timeScale().timeToCoordinate(timeSec);
    const y = candle.priceToCoordinate(price);
    if (x == null || y == null) return null;
    return { x, y };
}
function secOf(p) { return Math.floor(p.time / 1000); }

// 点到线段距离
function distToSeg(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1;
    const len2 = dx * dx + dy * dy;
    let t = len2 ? ((px - x1) * dx + (py - y1) * dy) / len2 : 0;
    t = Math.max(0, Math.min(1, t));
    const cx = x1 + t * dx, cy = y1 + t * dy;
    return Math.hypot(px - cx, py - cy);
}

// 命中检测：返回 {id, part:'body'|'p1'|'p2'} 或 null
function hitTest(x, y) {
    for (const d of Object.values(state.drawings || {})) {
        if (d.visible === false) continue;
        if (d.type === 'hline') {
            const pt = toXY(secOf(d.points[0]), d.points[0].price);
            if (!pt) continue;
            // 水平线：y 接近且 x 在绘图区内
            if (Math.abs(y - pt.y) <= BODY_R) return { id: d.id, part: 'body' };
        } else {
            const a = toXY(secOf(d.points[0]), d.points[0].price);
            const b = toXY(secOf(d.points[1]), d.points[1].price);
            if (!a || !b) continue;
            if (Math.hypot(x - a.x, y - a.y) <= ENDPOINT_R) return { id: d.id, part: 'p1' };
            if (Math.hypot(x - b.x, y - b.y) <= ENDPOINT_R) return { id: d.id, part: 'p2' };
            if (distToSeg(x, y, a.x, a.y, b.x, b.y) <= BODY_R) return { id: d.id, part: 'body' };
        }
    }
    return null;
}

// ---------- 控制点覆盖层 ----------
function ensureLayer() {
    const el = chartEl();
    if (!el) return null;
    if (!handlesLayer || !handlesLayer.isConnected) {
        handlesLayer = document.createElement('div');
        handlesLayer.className = 'draw-handles';
        el.appendChild(handlesLayer);
    }
    return handlesLayer;
}

function updateHandles() {
    const layer = ensureLayer();
    if (!layer) return;
    layer.innerHTML = '';
    const d = state.drawings && state.drawings[state.selectedDrawingId];
    if (!d || d.visible === false) return;

    const mk = (x, y, part) => {
        const h = document.createElement('div');
        h.className = 'draw-handle';
        h.style.left = `${x - 5}px`;
        h.style.top = `${y - 5}px`;
        h.dataset.part = part;
        layer.appendChild(h);
    };
    if (d.type === 'hline') {
        const pt = toXY(secOf(d.points[0]), d.points[0].price);
        if (pt) mk(40, pt.y, 'body');  // 水平线在左侧给一个拖拽把手
    } else {
        const a = toXY(secOf(d.points[0]), d.points[0].price);
        const b = toXY(secOf(d.points[1]), d.points[1].price);
        if (a) mk(a.x, a.y, 'p1');
        if (b) mk(b.x, b.y, 'p2');
    }
}

function clearSelection() {
    if (state.selectedDrawingId == null) return;
    state.selectedDrawingId = null;
    updateHandles();
}

// ---------- 持久化 ----------
function persist(d) {
    const url = `/api/drawing/${encodeURIComponent(d.id)}`;
    fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...d, board_id: state.currentBoard, timeframe: state.currentTimeframe }) })
        .then(r => r.json()).then(r => { if (r.error) log('error', `更新划线失败: ${r.error}`); });
}

// ---------- 拖拽 ----------
function setChartInteractive(on) {
    const chart = state.charts.main;
    if (!chart) return;
    chart.applyOptions(on
        ? { handleScroll: true, handleScale: { axisPressedMouseMove: { time: true, price: false }, axisDoubleClickReset: { time: true, price: true } } }
        : { handleScroll: false, handleScale: false });
}

function startDrag(hit, x, y) {
    const d = state.drawings[hit.id];
    drag = { id: hit.id, part: hit.part, x0: x, y0: y, orig: JSON.parse(JSON.stringify(d.points)) };
    setChartInteractive(false);
    document.body.style.cursor = 'grabbing';
}

function moveDrag(x, y) {
    if (!drag) return;
    const d = state.drawings[drag.id];
    const chart = state.charts.main, candle = state.series.candle;
    if (!d || !chart || !candle) return;
    const dx = x - drag.x0, dy = y - drag.y0;

    if (d.type === 'hline') {
        // 水平线整体上下移
        const origY = candle.priceToCoordinate(drag.orig[0].price);
        const price = candle.coordinateToPrice(origY + dy);
        if (price != null) d.points[0].price = +price;
    } else if (drag.part === 'body') {
        // 线段整体平移
        d.points = drag.orig.map(p => {
            const o = toXY(secOf(p), p.price);
            if (!o) return p;
            const t = chart.timeScale().coordinateToTime(o.x + dx);
            const pr = candle.coordinateToPrice(o.y + dy);
            return { time: t != null ? t * 1000 : p.time, price: pr != null ? +pr : p.price };
        });
    } else {
        // 端点拖动
        const idx = drag.part === 'p1' ? 0 : 1;
        const t = chart.timeScale().coordinateToTime(x);
        const pr = candle.coordinateToPrice(y);
        if (t != null) d.points[idx].time = t * 1000;
        if (pr != null) d.points[idx].price = +pr;
    }
    refreshDrawing(d);
    updateHandles();
}

function endDrag() {
    if (!drag) return;
    const d = state.drawings[drag.id];
    drag = null;
    setChartInteractive(true);
    document.body.style.cursor = '';
    if (d) persist(d);
}

// 原地刷新单条划线（不重建全部）
function refreshDrawing(d) {
    // 直接全量 sync 最简单可靠（划线数量少）
    import('./render.js').then(m => m.syncDrawings());
}

// ---------- 样式弹窗 ----------
function openStyleDialog(d) {
    document.querySelectorAll('.set-modal').forEach(e => e.remove());
    const mask = document.createElement('div');
    mask.className = 'set-modal';
    const panel = document.createElement('div');
    panel.className = 'set-panel';
    panel.innerHTML = `
        <div class="set-title">划线样式</div>
        <div class="set-row"><span class="set-key">颜色</span>
            <input type="color" id="ds-color" value="${d.color || '#ef5350'}"></div>
        <div class="set-row"><span class="set-key">粗细</span>
            <input type="number" id="ds-width" min="1" max="6" value="${d.lineWidth || 2}" style="width:60px"></div>
        <div class="set-row"><span class="set-key">线型</span>
            <select id="ds-style">
                <option value="solid" ${d.lineStyle === 'solid' || !d.lineStyle ? 'selected' : ''}>实线</option>
                <option value="dashed" ${d.lineStyle === 'dashed' ? 'selected' : ''}>虚线</option>
                <option value="dotted" ${d.lineStyle === 'dotted' ? 'selected' : ''}>点线</option>
            </select></div>
        <div class="set-row set-foot">
            <button class="set-btn primary" id="ds-save">保存</button>
            <button class="set-btn" id="ds-cancel">取消</button>
        </div>`;
    mask.appendChild(panel);
    document.body.appendChild(mask);
    panel.querySelector('#ds-cancel').onclick = () => mask.remove();
    panel.querySelector('#ds-save').onclick = () => {
        d.color = panel.querySelector('#ds-color').value;
        d.lineWidth = +panel.querySelector('#ds-width').value || 2;
        d.lineStyle = panel.querySelector('#ds-style').value;
        // TV 式：改过的样式成为该类型新划线的默认
        drawDefaults[d.type] = { color: d.color, lineWidth: d.lineWidth, lineStyle: d.lineStyle };
        persistDefaults();
        persist(d);
        import('./render.js').then(m => m.syncDrawings());
        mask.remove();
    };
}

// ---------- 右键菜单 ----------
function showDrawingMenu(x, y, d) {
    showContextMenu(x, y, [
        { label: '改变样式', onClick: () => openStyleDialog(d) },
        { label: '删除划线', danger: true, onClick: () => {
            fetch(`/api/drawing/${encodeURIComponent(d.id)}?board_id=${encodeURIComponent(state.currentBoard)}&timeframe=${encodeURIComponent(state.currentTimeframe)}`, { method: 'DELETE' })
                .then(r => r.json()).then(r => { if (r.error) log('error', `删除划线失败: ${r.error}`); });
            clearSelection();
        } },
    ]);
}

// ---------- 用户主动划线（TV 风格工具栏） ----------
function setCursor(c) { const el = chartEl(); if (el) el.style.cursor = c || ''; }

function refreshToolbar() {
    document.querySelectorAll('.draw-tool').forEach(b => {
        b.classList.toggle('active', b.dataset.tool === state.drawTool);
    });
}

export function setDrawTool(tool) {
    state.drawTool = (state.drawTool === tool) ? null : tool;
    state.drawAnchor = null;
    clearSelection();
    updatePreview(-1, -1);  // 清预览
    setCursor(state.drawTool ? 'crosshair' : '');
    refreshToolbar();
}

export function cancelDrawing() {
    state.drawTool = null;
    state.drawAnchor = null;
    updatePreview(-1, -1);
    setCursor('');
    refreshToolbar();
}

export function initDrawToolbar() {
    document.querySelectorAll('.draw-tool').forEach(b => {
        b.onclick = () => setDrawTool(b.dataset.tool);
    });
}

// 预览线（DOM 覆盖层）
function updatePreview(x, y) {
    const layer = ensureLayer();
    if (!layer) return;
    layer.querySelectorAll('.draw-preview').forEach(e => e.remove());
    if (!state.drawTool) return;

    // 预览辅助线样式 = 该工具默认样式（与画完后的线一致）
    const def = drawDefaults[state.drawTool] || { color: '#2962ff', lineWidth: 1, lineStyle: 'solid' };
    const cssLine = (s) => s === 'dashed' ? 'dashed' : s === 'dotted' ? 'dotted' : 'solid';
    const applyStyle = (el) => {
        el.style.borderTopColor = def.color;
        el.style.borderTopStyle = cssLine(def.lineStyle);
        el.style.borderTopWidth = `${def.lineWidth || 1}px`;
    };

    if (state.drawTool === 'hline') {
        if (y < 0) return;
        const p = document.createElement('div');
        p.className = 'draw-preview hline';
        p.style.top = `${y}px`;
        applyStyle(p);
        layer.appendChild(p);
    } else if (state.drawTool === 'trend') {
        // 锚点标记
        if (state.drawAnchor) {
            const a = toXY(secOf(state.drawAnchor), state.drawAnchor.price);
            if (a) {
                const dot = document.createElement('div');
                dot.className = 'draw-preview dot';
                dot.style.left = `${a.x - 4}px`; dot.style.top = `${a.y - 4}px`;
                dot.style.background = def.color;
                layer.appendChild(dot);
                if (x >= 0) {
                    const len = Math.hypot(x - a.x, y - a.y);
                    const ang = Math.atan2(y - a.y, x - a.x) * 180 / Math.PI;
                    const line = document.createElement('div');
                    line.className = 'draw-preview trend';
                    line.style.left = `${a.x}px`; line.style.top = `${a.y}px`;
                    line.style.width = `${len}px`;
                    line.style.transform = `rotate(${ang}deg)`;
                    applyStyle(line);
                    layer.appendChild(line);
                }
            }
        }
    }
}

function addDrawingRemote(drawing) {
    fetch('/api/drawing', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...drawing, board_id: state.currentBoard, timeframe: state.currentTimeframe }) })
        .then(r => r.json()).then(r => { if (r.error) log('error', `添加划线失败: ${r.error}`); });
}

function xyToTimePrice(x, y) {
    const chart = state.charts.main, candle = state.series.candle;
    const t = chart.timeScale().coordinateToTime(x);
    const p = candle.coordinateToPrice(y);
    return { time: t != null ? t * 1000 : null, price: p != null ? +p : null };
}

function handleDrawClick(x, y) {
    const tp = xyToTimePrice(x, y);
    const def = drawDefaults[state.drawTool] || { color: '#ef5350', lineWidth: 2, lineStyle: 'solid' };
    if (state.drawTool === 'hline') {
        if (tp.price == null) return;
        addDrawingRemote({ id: `d_${Date.now()}`, type: 'hline', points: [{ price: tp.price }], ...def });
        cancelDrawing();
    } else if (state.drawTool === 'trend') {
        if (!state.drawAnchor) {
            if (tp.time == null || tp.price == null) return;
            state.drawAnchor = { time: tp.time, price: tp.price };
            updatePreview(x, y);
        } else {
            if (tp.time == null || tp.price == null) return;
            addDrawingRemote({ id: `d_${Date.now()}`, type: 'trend',
                points: [state.drawAnchor, { time: tp.time, price: tp.price }], ...def });
            cancelDrawing();
        }
    }
}

// ---------- 事件绑定 ----------
export function attachDrawingInteraction() {
    const el = chartEl();
    if (!el) return;
    if (controller) controller.abort();
    controller = new AbortController();
    const sig = { signal: controller.signal };

    const local = (e) => {
        const r = el.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    // 双击选中（绘制模式下禁用）
    el.addEventListener('dblclick', (e) => {
        if (state.drawTool) return;
        const { x, y } = local(e);
        const hit = hitTest(x, y);
        state.selectedDrawingId = hit ? hit.id : null;
        updateHandles();
    }, sig);

    // 单击：绘制模式→落点；否则空白取消选中
    el.addEventListener('click', (e) => {
        const { x, y } = local(e);
        if (state.drawTool) { handleDrawClick(x, y); return; }
        if (!hitTest(x, y)) clearSelection();
    }, sig);

    // 按下：命中已选中线 → 开始拖拽（绘制模式下禁用）
    el.addEventListener('mousedown', (e) => {
        if (state.drawTool) return;
        if (e.button !== 0) return;
        const { x, y } = local(e);
        const hit = hitTest(x, y);
        if (hit && state.selectedDrawingId === hit.id) {
            e.preventDefault(); e.stopPropagation();
            startDrag(hit, x, y);
        }
    }, sig);

    window.addEventListener('mousemove', (e) => {
        if (drag) { const { x, y } = local(e); moveDrag(x, y); return; }
        if (state.drawTool) { const { x, y } = local(e); updatePreview(x, y); }
    }, sig);
    window.addEventListener('mouseup', () => endDrag(), sig);

    // 右键：绘制模式→取消；否则命中线弹菜单
    el.addEventListener('contextmenu', (e) => {
        if (state.drawTool) { e.preventDefault(); cancelDrawing(); return; }
        const { x, y } = local(e);
        const hit = hitTest(x, y);
        if (hit) {
            e.preventDefault(); e.stopPropagation();
            state.selectedDrawingId = hit.id;
            updateHandles();
            showDrawingMenu(e.clientX, e.clientY, state.drawings[hit.id]);
        }
    }, sig);

    // Esc 取消绘制
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && state.drawTool) cancelDrawing();
    }, sig);

    // 视口变化时重定位控制点
    state.charts.main && state.charts.main.timeScale().subscribeVisibleLogicalRangeChange(() => updateHandles(), );
    updateHandles();
}
