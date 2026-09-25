import { state } from './state.js';
import { log } from './log.js';
import { renderBoardTabs, renderTimeframeTabs, switchBoard, switchTimeframe, refreshIntervalOptions } from './ui.js';
import { renderChart, applyDataUpdate, syncDrawings, renderSubplots, captureSnapshot, setVisibleTimeRange } from './render.js';

    // ============================================================
    // WebSocket（v0.4 标准信封 {v,type,seq,ts,payload} 硬切）
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
            const env = JSON.parse(event.data);
            // 信封硬切：业务字段在 payload；缺 payload 的平铺消息视为非法（同版发布无混合）
            const msg = env && env.payload
                ? { ...env.payload, type: env.type, _seq: env.seq }
                : env;
            handleWsMessage(msg);
        };
    }

    function _syncLocks(boards) {
        state.locks = state.locks || {};
        (boards || []).forEach(b => { state.locks[b.id] = b.source_lock || null; });
    }

    function handleWsMessage(msg) {
        switch (msg.type) {
            case 'init':
                handleInit(msg);
                break;
            case 'ohlcv_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    // R8 差量合并：前插/追加/按 ts 替换
                    const prep = msg.prepended || [];
                    const app = msg.appended || [];
                    const upd = msg.updated || [];
                    if (prep.length) state.ohlcv = [...prep, ...state.ohlcv];
                    if (app.length) state.ohlcv = [...state.ohlcv, ...app];
                    if (upd.length) {
                        const idx = new Map(state.ohlcv.map((b, i) => [b.timestamp, i]));
                        for (const b of upd) {
                            const i = idx.get(b.timestamp);
                            if (i !== undefined) state.ohlcv[i] = b;
                        }
                    }
                    if (msg.markers) state.markers = msg.markers;
                    applyDataUpdate(prep.length);
                }
                log('ws', `ohlcv_update: ${msg.board_id}/${msg.timeframe} (+${(msg.prepended || []).length}/~${(msg.appended || []).length + (msg.updated || []).length})`);
                break;
            case 'indicator_add':
            case 'indicator_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.indicators[msg.inst_id] = {
                        inst_id: msg.inst_id, kind: msg.kind, script: msg.script,
                        values: msg.values, lines: msg.lines, markers: msg.markers,
                        subplot: msg.subplot, style: msg.style, lines_style: msg.lines_style,
                        scope: msg.scope, params: msg.params,
                        display_name: msg.display_name,
                    };
                    renderChart();
                }
                log('ws', `${msg.type}: ${msg.inst_id}`);
                break;
            case 'indicator_remove':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    delete state.indicators[msg.inst_id];
                    renderChart();
                }
                log('ws', `indicator_remove: ${msg.inst_id}`);
                break;
            case 'markers_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.markers = msg.markers;
                    renderChart();
                }
                log('ws', `markers_update: ${msg.markers?.length || 0} markers`);
                break;
            case 'drawing_add':
            case 'drawing_update':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    state.drawings[msg.drawing.id] = msg.drawing;
                    syncDrawings();
                }
                log('ws', `${msg.type}: ${msg.drawing.type} (${msg.drawing.id})`);
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
                _syncLocks([msg.board]);
                renderBoardTabs();
                log('ws', `board_create: ${msg.board.id}`);
                break;
            case 'board_remove':
                state.boards = state.boards.filter(b => b.id !== msg.board_id);
                delete state.locks[msg.board_id];
                if (!msg.current_board) {
                    // 删光 = 全白户：清当前视图数据 → renderChart 落引导页（不留旧K线残影）
                    state.currentBoard = null;
                    state.currentTimeframe = null;
                    applyState({});
                    renderBoardTabs();
                    renderTimeframeTabs();
                    renderChart();
                    } else if (msg.current_board !== state.currentBoard) {
                    // 删的是当前板且还有剩余：切过去（服务端广播 board_switch 带状态）
                    switchBoard(msg.current_board);
                    renderBoardTabs();
                } else {
                    renderBoardTabs();
                }
                log('ws', `board_remove: ${msg.board_id} → current=${msg.current_board}`);
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
                refreshIntervalOptions();
                log('ws', `board_switch: ${msg.board_id}`);
                break;
            case 'board_locked':
                state.locks = state.locks || {};
                state.locks[msg.board_id] = msg.source_lock;
                log('ws', `board_locked: ${msg.board_id} → ${msg.source_lock?.script}`);
                break;
            case 'kline_source_set':
                log('info', `kline_source: ${msg.board_id}/${msg.timeframe} → ${msg.script} (poll_s=${msg.poll_s ?? 'once'})`);
                break;
            case 'scripts_changed':
                log('info', `脚本库变化: ${msg.id}（搜索/列表下次读取生效）`);
                break;
            case 'timeframe_create':
                if (msg.board_id === state.currentBoard) {
                    const b = state.boards.find(x => x.id === state.currentBoard);
                    refreshIntervalOptions();  // 以服务端 interval_options.current 同步排序后的列表
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
                    refreshIntervalOptions();
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
            case 'view_set':
                if (msg.board_id === state.currentBoard && msg.timeframe === state.currentTimeframe) {
                    const fromSec = Math.floor((msg.from_time < 1e11 ? msg.from_time * 1000 : msg.from_time) / 1000);
                    const toSec = Math.ceil((msg.to_time < 1e11 ? msg.to_time * 1000 : msg.to_time) / 1000);
                    setVisibleTimeRange(fromSec, toSec);
                }
                log('ws', `view_set: ${msg.board_id}/${msg.timeframe} [${msg.from_time},${msg.to_time}]`);
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
        _syncLocks(state.boards);
        if (msg.data) {
            applyState(msg.data);
        }
        renderBoardTabs();
        renderTimeframeTabs();
        renderChart();
        refreshIntervalOptions();
        log('info', `初始化完成: ${state.currentBoard}/${state.currentTimeframe}`);
    }

    function applyState(data) {
        state.ohlcv = data.ohlcv || [];
        state.markers = data.markers || [];
        state.indicators = data.indicators || {};  // v0.4: inst_id 键
        state.drawings = {};
        (data.drawings || []).forEach(d => { state.drawings[d.id] = d; });
        state.subplots = {};
        (data.subplots || []).forEach(sp => {
            state.subplots[sp.name] = sp;
        });
    }

export { connectWebSocket, handleWsMessage, handleInit, applyState };
