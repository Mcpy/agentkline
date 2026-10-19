// ============================================================
// 指标库个人偏好（v0.5.4）：收藏 + 最近使用
// ------------------------------------------------------------
// 纯前端偏好：与语言（ak_lang）、画线样式一样存 localStorage，
// 不进服务端状态——板/指标仍以内核为唯一真源，重启不会复活已删指标。
// 结构：{ favorites: [script...], recent: [script...] }，均「最近在前」。
// 以 script（研究 id）为键，不含实例 id：同一研究多个实例合并成一条。
// 收藏顺序 = 用户加星顺序（新收藏在前）；最近使用 = 最近一次添加在前。
// ============================================================

const LS_KEY = 'ak.indicator.prefs.v1';
const MAX_RECENT = 8;

let _prefs = null;

function blank() {
    return { favorites: [], recent: [] };
}

function load() {
    if (_prefs) return _prefs;
    let raw = null;
    try {
        raw = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
    } catch (e) {
        raw = null;   // 存取被禁/内容损坏：退回空偏好，不影响指标库可用
    }
    _prefs = blank();
    if (raw && typeof raw === 'object') {
        if (Array.isArray(raw.favorites)) {
            _prefs.favorites = raw.favorites.filter(x => typeof x === 'string');
        }
        if (Array.isArray(raw.recent)) {
            _prefs.recent = raw.recent.filter(x => typeof x === 'string');
        }
    }
    _prefs.recent = _prefs.recent.slice(0, MAX_RECENT);
    return _prefs;
}

function save() {
    try {
        localStorage.setItem(LS_KEY, JSON.stringify(_prefs));
    } catch (e) {
        // 隐私模式/配额满：本次会话内仍可用，只是不落盘
    }
}

export function favoriteScripts() {
    return load().favorites.slice();
}

export function isFavorite(script) {
    return !!script && load().favorites.includes(script);
}

// 返回切换后的状态：true = 已收藏
export function toggleFavorite(script) {
    if (!script) return false;
    const p = load();
    const i = p.favorites.indexOf(script);
    if (i >= 0) p.favorites.splice(i, 1);
    else p.favorites.unshift(script);
    save();
    return i < 0;
}

export function recentScripts() {
    return load().recent.slice();
}

// 添加一个实例成功后调用；重复使用同一研究会提到队首，不重复占位
export function recordUse(script) {
    if (!script) return;
    const p = load();
    p.recent = [script, ...p.recent.filter(x => x !== script)].slice(0, MAX_RECENT);
    save();
}
