import { state } from './state.js';
import { log } from './log.js';
import { showContextMenu } from './menu.js';
import { openIdCard } from './render.js';

    // ============================================================
    // UI 渲染
    // ============================================================
    function renderBoardTabs() {
        const container = document.getElementById('board-tabs');
        container.innerHTML = '';
        state.boards.forEach(board => {
            const tab = document.createElement('div');
            tab.className = `board-tab ${board.id === state.currentBoard ? 'active' : ''}`;
            tab.textContent = board.name || board.id;
            tab.onclick = () => switchBoard(board.id);
            // 右键菜单：板身份证卡（锁信息入口，铭牌已撤）/ 删除画板
            tab.oncontextmenu = (e) => {
                e.preventDefault(); e.stopPropagation();
                const items = [];
                if ((state.locks || {})[board.id]) {
                    items.push({ label: '板身份证卡', onClick: () => openIdCard(board.id) });
                }
                items.push({ label: '删除画板', danger: true, onClick: () => deleteBoard(board.id) });
                showContextMenu(e.clientX, e.clientY, items);
            };
            container.appendChild(tab);
        });
    }

    function deleteBoard(boardId) {
        fetch(`/api/board/${boardId}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(d => { if (d.error) log('error', `删除画板失败: ${d.error}`); });
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
