// ============================================================
// 剪贴板（v0.6.4 打磨）：HTTP 页面没有 navigator.clipboard（非安全上下文）
// 先试 Clipboard API，失败/不存在则退回 textarea + execCommand('copy')
// ============================================================

export async function copyText(text) {
    const s = String(text == null ? '' : text);
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(s);
            return true;
        } catch (e) { /* 继续走 fallback（权限/策略拒绝） */ }
    }
    const ta = document.createElement('textarea');
    ta.value = s;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0;';
    document.body.appendChild(ta);
    const sel = document.getSelection();
    const prev = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
    ta.select();
    ta.setSelectionRange(0, s.length);
    let ok = false;
    try {
        ok = document.execCommand('copy');
    } catch (e) {
        ok = false;
    }
    ta.remove();
    if (prev && sel) {
        sel.removeAllRanges();
        sel.addRange(prev);
    }
    return ok;
}
