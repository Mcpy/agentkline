// v0.4.5 前端多语言核心（插件化）：语言包 = locales/i18n_xx.js（default export
// {code, name, fallback, table}），vite import.meta.glob 自动发现——新增语言零注册。
// 回退链：当前语言 → 包自声明 fallback → en → zh → key 原样。
// 切换 v1 = setLang + location.reload()（服务端态完整，重载无损）。

const packs = import.meta.glob('./locales/i18n_*.js', { eager: true });

const REG = {};   // code -> {code, name, fallback, table}
for (const [path, mod] of Object.entries(packs)) {
    const p = mod.default;
    if (p && p.code && p.table) REG[p.code] = p;
}

export function availableLangs() {
    return Object.values(REG).map(p => ({ code: p.code, name: p.name }));
}

const LS_KEY = 'ak_lang';

function detect() {
    const q = new URLSearchParams(location.search).get('lang');   // ?lang=xx 优先（分享链接带语言）
    if (q && REG[q]) return q;
    const saved = localStorage.getItem(LS_KEY);
    if (saved && REG[saved]) return saved;
    const nav = (navigator.language || '').toLowerCase();
    for (const code of Object.keys(REG)) {
        if (nav.startsWith(code)) return code;
    }
    return REG.zh ? 'zh' : (REG.en ? 'en' : Object.keys(REG)[0]);
}

let _lang = detect();
const _subs = [];

export function lang() { return _lang; }

export function setLang(l) {
    if (!REG[l]) return;
    localStorage.setItem(LS_KEY, l);
    _lang = l;
    _subs.forEach(f => { try { f(l); } catch (e) { /* 订阅方自保 */ } });
}

export function onLang(f) { _subs.push(f); }

function lookup(code, key) {
    const p = REG[code];
    return p ? p.table[key] : undefined;
}

export function t(key, params) {
    let s = lookup(_lang, key);
    if (s === undefined) {
        const fb = (REG[_lang] || {}).fallback;
        if (fb) s = lookup(fb, key);
    }
    if (s === undefined) s = lookup('en', key);
    if (s === undefined) s = lookup('zh', key);
    if (s === undefined) s = key;
    if (params) {
        for (const [k, v] of Object.entries(params)) {
            s = s.split('{' + k + '}').join(String(v));
        }
    }
    return s;
}

// ---- ②层：数据层 display 串的展示翻译（A 股专名保留中文=用户裁决 b 派） ----
// TAG 解析键 = binance/mock display 数据契约（TradFi永续/股票永续/ 现货/ 永续），\u 转义保门禁零字面量
const TAG_MAP = [['TradFi\u6c38\u7eed', 'tag.tradfi'], ['\u80a1\u7968\u6c38\u7eed', 'tag.stock'],
                 [' \u73b0\u8d27', 'tag.spot'], [' \u6c38\u7eed', 'tag.perp']];

export function localizeDisplay(d) {
    let s = d || '';
    for (const [k, key] of TAG_MAP) {
        if (s.endsWith(k)) { s = s.slice(0, -k.length).trimEnd() + ' ' + t(key); break; }
    }
    return s;
}

export function localizeBoardName(name) {
    const i = (name || '').indexOf(': ');
    return i > 0 ? name.slice(0, i + 2) + localizeDisplay(name.slice(i + 2))
                 : localizeDisplay(name);
}

// 静态层：data-i18n(文本) / data-i18n-title(title) / data-i18n-ph(placeholder) / data-i18n-html
export function applyStatic(root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
    root.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    root.querySelectorAll('[data-i18n-html]').forEach(el => { el.innerHTML = t(el.dataset.i18nHtml); });
}
