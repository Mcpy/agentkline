import './style.css';

import { state } from './state.js';
import { log, toggleLog } from './log.js';
import { connectWebSocket } from './ws.js';
import { bindSearch } from './search.js';
import { initDrawToolbar } from './draw_interact.js';
import { bindOverlays } from './render.js';

// ============================================================
// 初始化
// ============================================================
function init() {
    // 绑定日志面板折叠/展开（原 board.html 中 log-header 的 inline onclick="toggleLog()"）
    document.querySelector('.log-header').addEventListener('click', toggleLog);
    initDrawToolbar();
    bindSearch();
    bindOverlays();

    connectWebSocket();
    log('info', 'AgentKline 前端初始化完成');
    window.__cb = { state };  // 调试钩子

    // 心跳
    setInterval(() => {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            state.ws.send('ping');
        }
    }, 30000);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
