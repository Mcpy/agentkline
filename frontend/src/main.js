import './style.css';

import { state } from './state.js';
import { log, toggleLog } from './log.js';
import { connectWebSocket } from './ws.js';
import { bindSearch } from './search.js';
import { initDrawToolbar } from './draw_interact.js';
import { bindOverlays } from './render.js';
import { bindWatchlist } from './watchlist.js';
import { applyStatic, t, lang, setLang, availableLangs } from './i18n.js';
import { showContextMenu } from './menu.js';

// ============================================================
// 初始化
// ============================================================
function init() {
    // 绑定日志面板折叠/展开（原 board.html 中 log-header 的 inline onclick="toggleLog()"）
    document.querySelector('.log-header').addEventListener('click', toggleLog);
    initDrawToolbar();
    bindSearch();
    bindOverlays();
    bindWatchlist();

    // v0.4.5 语言切换（周期行右端；点击出下拉菜单，菜单项=语言本名，当前项 ✓）
    const langBtn = document.createElement('button');
    langBtn.id = 'lang-toggle'; langBtn.className = 'lang-toggle';
    const paintLang = () => {
        const cur = availableLangs().find(x => x.code === lang());
        langBtn.textContent = (cur ? cur.name : lang()) + ' \u25be';
        langBtn.title = t('bar.lang_title');
    };
    paintLang();
    langBtn.onclick = (e) => {
        e.stopPropagation();
        showContextMenu(e.clientX, e.clientY, availableLangs().map(x => ({
            label: (x.code === lang() ? '\u2713 ' : '') + x.name,
            onClick: () => { if (x.code !== lang()) { setLang(x.code); location.reload(); } },
        })));
    };
    const tfBar = document.querySelector('.timeframe-bar');
    tfBar.appendChild(langBtn);
    applyStatic();

    connectWebSocket();
    log('info', t('log.init'));
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
