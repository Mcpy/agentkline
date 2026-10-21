// ============================================================
// 应用内对话框：替代原生 prompt/confirm，风格与暗色面板一致
// openDialog({title, message?, value?, placeholder?, confirmText?, danger?})
//   - 有 value（含空串）= 输入框；无 value = 确认框
//   - 返回 Promise：输入框 → 字符串 / null；确认框 → true / null
// ============================================================
import { t } from './i18n.js';

let _active = false;

export function openDialog(opts = {}) {
    if (_active) return Promise.resolve(null);
    const {
        title = '', message = '', value = null, placeholder = '',
        confirmText = t('common.ok'), danger = false,
    } = opts;
    const hasInput = value !== null;
    _active = true;

    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'overlay dialog-overlay';

        const card = document.createElement('div');
        card.className = 'overlay-card dialog-card';
        card.setAttribute('role', 'dialog');
        card.setAttribute('aria-modal', 'true');

        const h = document.createElement('h3');
        h.textContent = title;
        card.appendChild(h);

        if (message) {
            const p = document.createElement('div');
            p.className = 'dialog-msg';
            p.textContent = message;
            card.appendChild(p);
        }

        let input = null;
        if (hasInput) {
            input = document.createElement('input');
            input.className = 'dialog-input';
            input.type = 'text';
            input.value = String(value);
            if (placeholder) input.placeholder = placeholder;
            card.appendChild(input);
        }

        const foot = document.createElement('div');
        foot.className = 'dialog-foot';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'btn-ghost';
        cancel.textContent = t('common.cancel');
        const ok = document.createElement('button');
        ok.type = 'button';
        ok.className = danger ? 'btn-danger' : 'btn-primary';
        ok.textContent = confirmText;
        foot.append(cancel, ok);
        card.appendChild(foot);
        overlay.appendChild(card);

        const close = (val) => {
            if (!_active) return;
            _active = false;
            document.removeEventListener('keydown', onKey, true);
            overlay.remove();
            resolve(val);
        };
        const submit = () => {
            if (!hasInput) { close(true); return; }
            const v = input.value.trim();
            if (!v) { input.focus(); return; }
            close(v);
        };
        const syncOk = () => {
            if (hasInput) ok.disabled = !input.value.trim();
        };
        const onKey = (e) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                close(null);
            } else if (e.key === 'Enter' && hasInput) {
                e.preventDefault();
                submit();
            }
        };

        if (hasInput) {
            input.addEventListener('input', syncOk);
            syncOk();
        }
        cancel.addEventListener('click', () => close(null));
        ok.addEventListener('click', submit);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(null); });
        document.addEventListener('keydown', onKey, true);

        document.body.appendChild(overlay);
        (input || ok).focus();
        if (input) input.select();
    });
}
