// ============================================================
// 右键上下文菜单（画板/指标的删除等交互）
// ============================================================
let menuEl = null;

function hideContextMenu() {
    if (menuEl) { menuEl.remove(); menuEl = null; }
}

// items: [{label, danger?, onClick}]
function showContextMenu(x, y, items) {
    hideContextMenu();
    menuEl = document.createElement('div');
    menuEl.className = 'ctx-menu';
    items.forEach(it => {
        const el = document.createElement('div');
        el.className = `ctx-item${it.danger ? ' danger' : ''}`;
        el.textContent = it.label;
        el.onclick = (e) => { e.stopPropagation(); hideContextMenu(); if (it.onClick) it.onClick(); };
        menuEl.appendChild(el);
    });
    document.body.appendChild(menuEl);
    // 边界修正，避免菜单超出屏幕
    const r = menuEl.getBoundingClientRect();
    if (x + r.width > innerWidth) x = Math.max(4, innerWidth - r.width - 4);
    if (y + r.height > innerHeight) y = Math.max(4, innerHeight - r.height - 4);
    menuEl.style.left = `${x}px`;
    menuEl.style.top = `${y}px`;
}

// 全局关闭：点击别处 / Esc / 失焦 / 滚动
document.addEventListener('click', hideContextMenu);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideContextMenu(); });
window.addEventListener('blur', hideContextMenu);
// v0.4.3 bug2：wheel 关闭退役——下拉菜单项超出视口时滚轮查看会误关菜单
// （SDK scrollIntoView 与真人滚轮同中招）；Esc/点别处/失焦关闭保留

export { showContextMenu, hideContextMenu };
