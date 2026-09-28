import { state, applyState } from './state.js';
import { log } from './log.js';
import { showContextMenu } from './menu.js';
import { openIdCard, renderChart } from './render.js';  // v0.4.2 fix: deleteBoard 删光路径调 renderChart，漏 import 曾致 ReferenceError 断链（老 bug1 回归真根因之一）


    // ============================================================
    // UI 渲染
    // ============================================================
    const TAB_MAX = 8;  // v0.4.4 C 案：明排上限，溢出收下拉

    // v0.4.4 tab 短名：去源 stem → 摘 tag → 去 /USDT → CJK 取首段 / 拉丁取末段
    function shortBoardName(name) {
        let t = (name || '').split(':').slice(1).join(':').trim() || name || '';
        let tag = '';
        for (const [k, v] of [['TradFi永续', 'TradFi'], ['股票永续', '股票'], [' 现货', '现货'], [' 永续', '永续']]) {
            if (t.endsWith(k)) { tag = v; t = t.slice(0, -k.length).trim(); break; }
        }
        t = t.replace(/\/USDT$/, '').trim();
        const parts = t.split(/\s+/).filter(Boolean);
        let core = parts.length && /[\u4e00-\u9fa5]/.test(parts[0]) ? parts[0]
                 : (parts[parts.length - 1] || t);
        return (core + (tag ? ' ' + tag : '')).trim() || name || '';
    }

    function closeOverflow() {
        const m = document.getElementById('board-overflow-menu');
        if (m) m.remove();
    }

    function openOverflowMenu(anchor, overflow) {
        closeOverflow();
        const m = document.createElement('div');
        m.className = 'tf-menu'; m.id = 'board-overflow-menu';
        overflow.forEach(b => {
            const row = document.createElement('div');
            row.className = 'tf-menu-item ov-row';
            const nm = document.createElement('span');
            nm.className = 'ov-name' + (b.id === state.currentBoard ? ' ov-cur' : '');
            nm.textContent = b.name || b.id;
            const x = document.createElement('span');
            x.className = 'ov-x'; x.textContent = '×'; x.title = '删除画板';
            x.onclick = (e) => { e.stopPropagation(); closeOverflow(); deleteBoard(b.id); };
            row.append(nm, x);
            row.onclick = () => { closeOverflow(); switchBoard(b.id); };
            m.appendChild(row);
        });
        const r = anchor.getBoundingClientRect();
        m.style.position = 'fixed';
        m.style.left = Math.max(4, r.right - 260) + 'px';
        m.style.top = (r.bottom + 4) + 'px';
        document.body.appendChild(m);
        setTimeout(() => document.addEventListener('click', closeOverflow, { once: true }), 0);
    }

    function tabEl(board) {
        const tab = document.createElement('div');
        tab.className = `board-tab ${board.id === state.currentBoard ? 'active' : ''}`;
        tab.textContent = shortBoardName(board.name || board.id);
        tab.title = board.name || board.id;   // 全名 tooltip
        tab.onclick = () => switchBoard(board.id);
            // 右键菜单：板身份证卡（锁信息入口，铭牌已撤）/ 删除画板
            tab.oncontextmenu = (e) => {
                e.preventDefault(); e.stopPropagation();
                const items = [];
                if ((state.locks || {})[board.id]) {
                    items.push({ label: '板身份证卡', onClick: () => openIdCard(board.id) });
                }
                const lk = (state.locks || {})[board.id] || {};
                if (lk.script && (lk.identity || {}).symbol) {
                    items.push({ label: '加入雷达', onClick: () => {
                        fetch('/api/watchlist/rows', { method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ source: lk.script, symbol: lk.identity.symbol }) })
                            .then(r => r.json()).then(d => { if (d.error) log('error', d.error); });
                    } });
                }
                items.push({ label: '删除画板', danger: true, onClick: () => deleteBoard(board.id) });
                showContextMenu(e.clientX, e.clientY, items);
            };
        return tab;
    }

    function renderBoardTabs() {
        const container = document.getElementById('board-tabs');
        container.innerHTML = '';
        const boards = state.boards;
        let visible = boards.slice(0, TAB_MAX);
        const cur = boards.find(b => b.id === state.currentBoard);
        if (cur && !visible.includes(cur)) {
            visible = boards.slice(0, TAB_MAX - 1).concat([cur]);  // 当前板永远明排
        }
        const overflow = boards.filter(b => !visible.includes(b));
        visible.forEach(b => container.appendChild(tabEl(b)));
        if (overflow.length) {
            const ob = document.createElement('div');
            ob.className = 'board-tab board-overflow' +
                (cur && overflow.includes(cur) ? ' on' : '');
            ob.textContent = `…+${overflow.length} ▾`;
            ob.title = '更多画板';
            ob.onclick = (e) => { e.stopPropagation(); openOverflowMenu(ob, overflow); };
            container.appendChild(ob);
        }
    }

    function deleteBoard(boardId) {
        fetch(`/api/board/${boardId}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(d => {
                if (d.error) { log('error', `删除画板失败: ${d.error}`); return; }
                // 乐观更新：本客户端标签立即消失，不等 WS（WS 断连/漏推也自洽；
                // 其他客户端靠 board_remove 广播，重连靠 init 全量同步）
                state.boards = state.boards.filter(b => b.id !== boardId);
                delete state.locks[boardId];
                renderBoardTabs();
                if (state.currentBoard === boardId) {
                    const nxt = state.boards[0];
                    if (nxt) {
                        fetch(`/api/board/${nxt.id}`);  // 服务端广播 board_switch 带状态
                    } else {
                        state.currentBoard = null;
                        state.currentTimeframe = null;
                        applyState({});
                        renderTimeframeTabs();
                        renderChart();   // 删光落引导页
                    }
                }
            });
    }

    function renderTimeframeTabs() {
        const container = document.getElementById('timeframe-tabs');
        container.innerHTML = '';
        const board = state.boards.find(b => b.id === state.currentBoard);
        if (!board) return;

        (board.intervals || []).forEach(tf => {
            const tab = document.createElement('div');
            tab.className = `tf-tab ${tf === state.currentTimeframe ? 'active' : ''}`;
            tab.textContent = tf;
            tab.onclick = () => switchTimeframe(tf);
            // 右键菜单：删除周期
            tab.oncontextmenu = (e) => {
                e.preventDefault(); e.stopPropagation();
                showContextMenu(e.clientX, e.clientY, [
                    { label: '删除周期', danger: true, onClick: () => deleteTimeframe(tf) },
                ]);
            };
            container.appendChild(tab);
        });

        // 优化点2：锁定现场（实时源）显示"+"添加支持周期；离线板不显示
        if ((state.locks || {})[state.currentBoard]) {
            const add = document.createElement('div');
            add.className = 'tf-tab tf-add';
            add.textContent = '+';
            add.title = '添加周期（仅实时源）';
            add.onclick = () => openIntervalMenu(add);
            container.appendChild(add);
        }
    }

    async function openIntervalMenu(anchor) {
        let opts = state.intervalOptions;
        if (!opts || opts.current !== undefined && opts._stale) opts = null;
        if (!opts) {
            try {
                opts = await fetch(`/api/board/${state.currentBoard}/interval_options`).then(r => r.json());
                state.intervalOptions = opts;
            } catch (e) { return; }
        }
        closeIntervalMenu();
        if (!opts.online) { log('info', '离线源不支持添加周期'); return; }
        if (!opts.addable || !opts.addable.length) { log('info', '支持的周期已全部添加'); return; }
        const menu = document.createElement('div');
        menu.className = 'tf-menu'; menu.id = 'tf-menu';
        opts.addable.forEach(iv => {
            const item = document.createElement('div');
            item.className = 'tf-menu-item';
            item.textContent = iv;
            item.onclick = () => {
                closeIntervalMenu();
                fetch(`/api/board/${state.currentBoard}/timeframe`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ interval: iv }) })
                    .then(r => r.json())
                    .then(d => { if (d.error) log('error', `加周期失败: ${d.error}`); });
            };
            menu.appendChild(item);
        });
        const rect = anchor.getBoundingClientRect();
        menu.style.left = rect.left + 'px';
        menu.style.top = (rect.bottom + 4) + 'px';
        document.body.appendChild(menu);
        setTimeout(() => document.addEventListener('click', closeIntervalMenu, { once: true }), 0);
    }

    function closeIntervalMenu() {
        const m = document.getElementById('tf-menu');
        if (m) m.remove();
    }

    async function refreshIntervalOptions() {
        if (!state.currentBoard) { state.intervalOptions = null; return; }
        try {
            state.intervalOptions = await fetch(`/api/board/${state.currentBoard}/interval_options`).then(r => r.json());
            const b = state.boards.find(x => x.id === state.currentBoard);
            if (b && state.intervalOptions && state.intervalOptions.current) {
                b.intervals = state.intervalOptions.current;  // 服务端排序为准
            }
        } catch (e) {
            state.intervalOptions = null;
        }
        renderTimeframeTabs();
    }

    function deleteTimeframe(tf) {
        fetch(`/api/board/${state.currentBoard}/timeframe/${tf}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(d => { if (d.error) log('error', `删除周期失败: ${d.error}`); });
    }

    function switchBoard(boardId) {
        fetch(`/api/board/${boardId}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    log('error', `切换画板失败: ${data.error}`);
                }
            });
    }

    function switchTimeframe(tf) {
        fetch(`/api/board/${state.currentBoard}/timeframe/${tf}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    log('error', `切换时间周期失败: ${data.error}`);
                }
            });
    }

export { renderBoardTabs, renderTimeframeTabs, switchBoard, switchTimeframe, refreshIntervalOptions };
