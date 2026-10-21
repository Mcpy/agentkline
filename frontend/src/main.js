import './style.css';

import { state } from './state.js';
import { log } from './log.js';
import { connectWebSocket } from './ws.js';
import { bindSearch } from './search.js';
import { bindOverlays } from './render.js';
import { bindWatchlist } from './watchlist.js';
import { applyStatic, t, lang, setLang, availableLangs } from './i18n.js';
import { showContextMenu } from './menu.js';
import { bindResults } from './results.js';
import { bindWorkbench } from './workbench.js';

// ============================================================
// 初始化
// ============================================================
async function loadUiConfig() {
    try {
        const r = await fetch('/api/config', { cache: 'no-store' });
        if (!r.ok) return;
        const j = await r.json();
        const tz = j && j.ui && j.ui.timezone;
        if (typeof tz === 'string' && tz) state.uiTimezone = tz;
    } catch (e) { /* 取不到就沿用默认 Asia/Shanghai */ }
}

async function init() {
    bindSearch();
    bindOverlays();
    bindWatchlist();
    bindResults();
    bindWorkbench();

    // v0.4.5 语言切换（0.6.0 起在顶栏右端；点击出下拉菜单，菜单项=语言本名，当前项 ✓）
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
    // 0.6.0：状态标识移除后，语言切换移到顶栏右端（原周期行右端）
    document.querySelector('.toolbar').appendChild(langBtn);
    applyStatic();

    // 0.6.0：先取界面时区，建图前生效（图表轴/读数/状态条同一时区）
    await loadUiConfig();
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
