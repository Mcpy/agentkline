import { state } from './state.js';
import { log } from './log.js';
import { showContextMenu } from './menu.js';

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
            // 右键菜单：删除画板
            tab.oncontextmenu = (e) => {
                e.preventDefault(); e.stopPropagation();
                showContextMenu(e.clientX, e.clientY, [
                    { label: '删除画板', danger: true, onClick: () => deleteBoard(board.id) },
                ]);
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

export { renderBoardTabs, renderTimeframeTabs, switchBoard, switchTimeframe };
