import { state } from './state.js';
import { log } from './log.js';
import { renderBoardTabs, renderTimeframeTabs, switchTimeframe } from './ui.js';
import { renderChart, applyDataUpdate, syncDrawings, renderSubplots, captureSnapshot } from './render.js';

    // ============================================================
    // WebSocket
    // ============================================================
    function connectWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/ws`;

        state.ws = new WebSocket(wsUrl);

        state.ws.onopen = () => {
            document.getElementById('ws-status').className = 'connected';
            document.getElementById('ws-status').textContent = '● 已连接';
            log('ws', 'WebSocket 已连接');
        };

        state.ws.onclose = () => {
            document.getElementById('ws-status').className = 'disconnected';
            document.getElementById('ws-status').textContent = '● 已断开';
            log('ws', 'WebSocket 断开，5秒后重连...');
            setTimeout(connectWebSocket, 5000);
        };

        state.ws.onerror = (e) => {
            log('error', 'WebSocket 错误');
        };

        state.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            handleWsMessage(msg);
        };
    }

    function handleWsMessage(msg) {
        switch (msg.type) {
            case 'init':
                handleInit(msg);
                break;
            case 'ohlcv_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.ohlcv = msg.data;
                    state.markers = msg.markers || [];
                    applyDataUpdate(msg.prepended || 0);
                }
                log('ws', `ohlcv_update: ${msg.board_id}/${msg.timeframe} (${msg.data?.length || 0} bars)`);
                break;
            case 'indicator_add':
            case 'indicator_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    const prev = state.indicators[msg.name] || {};
                    state.indicators[msg.name] = {
                        name: msg.name,
                        values: msg.values,
                        subplot: msg.subplot,
                        style: msg.style,
                        type: msg.indicator_type,
                        markers: msg.markers,
                        lines: msg.lines,
                        scope: msg.scope,
                        display_name: msg.display_name,
                        params: msg.params !== undefined ? msg.params : prev.params
                    };
                    renderChart();
                }
                log('ws', `${msg.type}: ${msg.name}`);
                break;
            case 'indicator_refresh':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    if (state.indicators[msg.name]) {
                        if (msg.lines) {
                            state.indicators[msg.name].lines = msg.lines;
                            state.indicators[msg.name].values = null;
                        } else {
                            state.indicators[msg.name].values = msg.values;
                        }
                        if (msg.display_name) state.indicators[msg.name].display_name = msg.display_name;
                        applyDataUpdate();
                    }
                }
                log('ws', `indicator_refresh: ${msg.name}`);
                break;
            case 'indicator_remove':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    delete state.indicators[msg.name];
                    renderChart();
                }
                log('ws', `indicator_remove: ${msg.name}`);
                break;
            case 'markers_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.markers = msg.markers;
                    renderChart();
                }
                log('ws', `markers_update: ${msg.markers?.length || 0} markers`);
                break;
            case 'drawing_add':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.drawings[msg.drawing.id] = msg.drawing;
                    syncDrawings();
                }
                log('ws', `drawing_add: ${msg.drawing.type} (${msg.drawing.id})`);
                break;
            case 'drawing_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.drawings[msg.drawing.id] = msg.drawing;
                    syncDrawings();
                }
                log('ws', `drawing_update: ${msg.drawing.id}`);
                break;
            case 'drawing_remove':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    delete state.drawings[msg.id];
                    syncDrawings();
                }
                log('ws', `drawing_remove: ${msg.id}`);
                break;
            case 'board_create':
                state.boards.push(msg.board);
                renderBoardTabs();
                log('ws', `board_create: ${msg.board.id}`);
                break;
            case 'board_remove':
                state.boards = state.boards.filter(b => b.id !== msg.board_id);
                state.currentBoard = msg.current_board;
                renderBoardTabs();
                log('ws', `board_remove: ${msg.board_id}`);
                break;
            case 'board_switch':
                state.currentBoard = msg.board_id;
                if (msg.timeframe) state.currentTimeframe = msg.timeframe;
                if (msg.state) {
                    applyState(msg.state);
                }
                renderBoardTabs();
                renderTimeframeTabs();
                renderChart();
                log('ws', `board_switch: ${msg.board_id}`);
                break;
            case 'timeframe_create':
                if (msg.board_id === state.currentBoard) {
                    const b = state.boards.find(x => x.id === state.currentBoard);
                    if (b && !(b.intervals || []).includes(msg.interval)) (b.intervals ||= []).push(msg.interval);
                    renderTimeframeTabs();
                }
                log('ws', `timeframe_create: ${msg.board_id}/${msg.interval}`);
                break;
            case 'timeframe_remove':
                if (msg.board_id === state.currentBoard) {
                    const wasCurrent = msg.interval === state.currentTimeframe;
                    const b = state.boards.find(x => x.id === state.currentBoard);
                    if (b) b.intervals = (b.intervals || []).filter(i => i !== msg.interval);
                    state.currentTimeframe = msg.default_timeframe;
                    renderTimeframeTabs();
                    // 删的是当前周期 → 拉取新默认周期的状态并重绘
                    if (wasCurrent && state.currentTimeframe) switchTimeframe(state.currentTimeframe);
                }
                log('ws', `timeframe_remove: ${msg.board_id}/${msg.interval}`);
                break;
            case 'timeframe_switch':
                if (msg.board_id === state.currentBoard) {
                    state.currentTimeframe = msg.timeframe;
                    if (msg.state) {
                        applyState(msg.state);
                    }
                    renderTimeframeTabs();
                    renderChart();
                }
                log('ws', `timeframe_switch: ${msg.board_id}/${msg.timeframe}`);
                break;
            case 'subplot_create':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.subplots[msg.name] = { name: msg.name, height: msg.height, title: msg.title };
                    renderSubplots();
                }
                log('ws', `subplot_create: ${msg.name}`);
                break;
            case 'subplot_remove':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    delete state.subplots[msg.name];
                    renderSubplots();
                }
                log('ws', `subplot_remove: ${msg.name}`);
                break;
            case 'datasource_start':
                log('info', `数据源启动: ${msg.board_id}/${msg.timeframe} (间隔 ${msg.poll_interval || '一次性'}s)`);
                break;
            case 'datasource_stop':
                log('info', `数据源停止: ${msg.board_id}/${msg.timeframe}`);
                break;
            case 'datasource_error':
                log('error', `数据源错误: ${msg.board_id}/${msg.timeframe}: ${msg.error}`);
                break;
            case 'snapshot_request':
                captureSnapshot();
                log('ws', 'snapshot_request: 截图并上传');
                break;
            case 'pong':
                break;
            default:
                log('ws', `未知消息: ${msg.type}`);
        }
    }

    function handleInit(msg) {
        state.boards = msg.boards || [];
        state.currentBoard = msg.board_id;
        state.currentTimeframe = msg.timeframe;
        if (msg.data) {
            applyState(msg.data);
        }
        renderBoardTabs();
        renderTimeframeTabs();
        renderChart();
        log('info', `初始化完成: ${state.currentBoard}/${state.currentTimeframe}`);
    }

    function applyState(data) {
        state.ohlcv = data.ohlcv || [];
        state.markers = data.markers || [];
        state.indicators = data.indicators || {};
        state.drawings = {};
        (data.drawings || []).forEach(d => { state.drawings[d.id] = d; });
        state.subplots = {};
        (data.subplots || []).forEach(sp => {
            state.subplots[sp.name] = sp;
        });
    }

export { connectWebSocket, handleWsMessage, handleInit, applyState };
