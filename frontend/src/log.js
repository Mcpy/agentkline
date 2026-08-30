    // ============================================================
    // 日志
    // ============================================================
    function log(type, message) {
        const content = document.getElementById('log-content');
        const time = new Date().toLocaleTimeString();
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = `<span class="time">[${time}]</span> <span class="type-${type}">${type.toUpperCase()}</span> ${message}`;
        content.appendChild(entry);
        content.scrollTop = content.scrollHeight;

        // 限制日志数量
        while (content.children.length > 200) {
            content.removeChild(content.firstChild);
        }
    }

    function toggleLog() {
        const panel = document.getElementById('log-panel');
        const content = document.getElementById('log-content');
        const toggle = document.getElementById('log-toggle');
        panel.classList.toggle('collapsed');
        content.classList.toggle('collapsed');
        toggle.textContent = panel.classList.contains('collapsed') ? '▲' : '▼';
    }

export { log, toggleLog };
