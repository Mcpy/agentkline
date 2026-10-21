// ============================================================
// 指标库面板（v0.5.3）：搜索 + 分类 + 多列网格
// ------------------------------------------------------------
// 背景：Vela 74 个经典研究 + KDJ 扩展后，旧的单列右键菜单放不下。
// 数据源：GET /api/indicator-catalog（indicator_spec.json，含参数 schema）。
// 交互：点卡片 = 加一个实例（Vela 研究本就多实例）；右上 × = 移除该研究的全部实例。
// 面板保持打开，支持连续添加；Esc/遮罩/× 关闭。
// ============================================================
import { state } from './state.js';
import { t, lang } from './i18n.js';
import { log } from './log.js';
import {
    favoriteScripts, isFavorite, toggleFavorite, recentScripts, recordUse,
} from './indicator_prefs.js';

let _catalog = null;          // 缓存目录（进程内不变）
let _nav = 'all';             // all | added | <group id>
let _query = '';
let _onChange = null;         // 变更回调（render.js 注入，避免反向 import）
let _activeClose = null;      // 已打开面板的关闭器（重复打开先收旧面板/旧 keydown）

async function loadCatalog(force = false) {
    if (_catalog && !force) return _catalog;   // 每次打开强制刷新：自定义脚本保存后立即可见
    const r = await fetch('/api/indicator-catalog');
    if (!r.ok) throw new Error(`catalog ${r.status}`);
    _catalog = await r.json();
    state.indicatorCatalog = _catalog;
    return _catalog;
}

function instsOf(script) {
    return Object.entries(state.indicators || {})
        .filter(([, ind]) => (ind.script || '') === script)
        .map(([id]) => id);
}

function needBoard() {
    if (state.currentBoard) return false;
    log('info', t('ind.need_board'));
    return true;
}

async function addOne(meta) {
    const r = await fetch('/api/indicator', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            board_id: state.currentBoard,
            timeframe: state.currentTimeframe,
            script: meta.script,
        }),
    });
    if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        log('error', d.detail || d.error || t('lib.add_fail', { name: meta.title_zh }));
        return false;
    }
    recordUse(meta.script);   // v0.5.4：最近使用 = 最近一次成功添加
    return true;
}

async function removeAll(meta) {
    const ids = instsOf(meta.script);
    if (!ids.length) return;
    await Promise.all(ids.map(id => fetch(
        `/api/indicator/${encodeURIComponent(id)}?board_id=${encodeURIComponent(state.currentBoard)}`
        + `&timeframe=${encodeURIComponent(state.currentTimeframe)}`,
        { method: 'DELETE' },
    ).catch(() => null)));
    log('info', t('lib.removed', { name: meta.title_zh, n: ids.length }));
}

export async function openIndicatorLibrary(onChange) {
    if (needBoard()) return;
    if (_activeClose) { try { _activeClose(); } catch (e) {} _activeClose = null; }
    // 每次打开都回到初始视图：关闭时输入的搜索词/分类不跨会话残留
    _query = '';
    _nav = 'all';
    _onChange = onChange || null;
    const catalog = await loadCatalog(true).catch((e) => {
        log('error', t('lib.load_fail', { e: e.message || e }));
        return null;
    });
    if (!catalog) return;

    document.querySelectorAll('.ind-lib-modal').forEach(e => e.remove());

    const modal = document.createElement('div');
    modal.className = 'ind-lib-modal';
    const panel = document.createElement('div');
    panel.className = 'ind-lib-panel';
    modal.appendChild(panel);

    // ---- 顶栏 ----
    const head = document.createElement('div');
    head.className = 'ind-lib-head';
    const title = document.createElement('div');
    title.className = 'ind-lib-title';
    title.textContent = t('lib.title');
    const search = document.createElement('input');
    search.className = 'ind-lib-search';
    search.type = 'search';
    search.placeholder = t('lib.search');
    const close = document.createElement('button');
    close.className = 'ind-lib-close';
    close.textContent = '×';
    close.title = t('lib.close');
    head.appendChild(title); head.appendChild(search); head.appendChild(close);
    panel.appendChild(head);

    // ---- 主体：左分类 + 右网格 ----
    const body = document.createElement('div');
    body.className = 'ind-lib-body';
    const nav = document.createElement('nav');
    nav.className = 'ind-lib-nav';
    const grid = document.createElement('div');
    grid.className = 'ind-lib-grid';
    body.appendChild(nav); body.appendChild(grid);
    panel.appendChild(body);

    // ---- 底栏提示 ----
    const foot = document.createElement('div');
    foot.className = 'ind-lib-foot';
    foot.textContent = t('lib.hint');
    panel.appendChild(foot);

    // 面板开着时，WS 增删实例 → 即时刷新卡片「已添加」/左侧计数（不再要求关闭重开）
    const onIndicatorsChanged = () => { renderNav(); renderGrid(true); };
    window.addEventListener('ak:indicators-changed', onIndicatorsChanged);
    const closeModal = () => {
        modal.remove();
        document.removeEventListener('keydown', onKey);
        window.removeEventListener('ak:indicators-changed', onIndicatorsChanged);
        if (_activeClose === closeModal) _activeClose = null;
    };
    _activeClose = closeModal;
    const onKey = (e) => { if (e.key === 'Escape') closeModal(); };
    close.onclick = closeModal;
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };
    document.addEventListener('keydown', onKey);
    search.oninput = () => {
        _query = search.value.trim().toLowerCase();
        if (_query) _nav = 'all';   // 搜索=全局，分类高亮同步归位
        renderNav(); renderGrid();
    };

    const groupLabel = (id) => {
        const g = (catalog.groups || []).find(x => x.id === id);
        return g ? (t('lib.group_' + g.id) || g.label) : id;
    };

    function matches(meta) {
        if (!_query) return true;
        const hay = [meta.type, meta.script, meta.title, meta.title_zh, meta.short, meta.desc]
            .join(' ').toLowerCase();
        return hay.includes(_query);
    }

    function renderNav() {
        const groups = catalog.groups || [];
        const favSet = new Set(favoriteScripts());
        const recentSet = new Set(recentScripts());
        const items = [
            { id: 'all', label: t('lib.all'), count: catalog.indicators.length },
            // v0.5.4：个人偏好入口置顶（空时也保留，便于发现）
            { id: 'favorites', label: t('lib.favorites'),
              count: catalog.indicators.filter(m => favSet.has(m.script)).length },
            { id: 'recent', label: t('lib.recent'),
              count: catalog.indicators.filter(m => recentSet.has(m.script)).length },
            { id: 'added', label: t('lib.added'),
              count: catalog.indicators.filter(m => instsOf(m.script).length).length },
            ...groups.map(g => ({
                id: g.id,
                label: groupLabel(g.id),
                count: catalog.indicators.filter(m => m.group === g.id).length,
            })),
        ];
        nav.innerHTML = '';
        items.forEach(it => {
            const b = document.createElement('button');
            b.className = `ind-lib-nav-item${_nav === it.id ? ' on' : ''}`;
            b.textContent = `${it.label} ${it.count}`;
            b.onclick = () => { _nav = it.id; renderNav(); renderGrid(); };
            nav.appendChild(b);
        });
    }

    function renderGrid(keepScroll = false) {
        const top = grid.scrollTop;
        // 有搜索词时跨分类检索（分类只作浏览过滤，避免「搜不到」）
        const scope = _query ? 'all' : _nav;
        let list = catalog.indicators.filter(m => {
            if (!matches(m)) return false;
            if (scope === 'all') return true;
            if (scope === 'added') return instsOf(m.script).length > 0;
            if (scope === 'favorites') return isFavorite(m.script);
            if (scope === 'recent') return recentScripts().includes(m.script);
            return m.group === scope;
        });
        // 收藏/最近按「加星/使用」倒序展示；其余保持目录序
        if (scope === 'favorites' || scope === 'recent') {
            const order = scope === 'favorites' ? favoriteScripts() : recentScripts();
            const idx = new Map(order.map((s, i) => [s, i]));
            list = list.slice().sort((a, b) => idx.get(a.script) - idx.get(b.script));
        }
        grid.innerHTML = '';
        if (!list.length) {
            const empty = document.createElement('div');
            empty.className = 'ind-lib-empty';
            empty.textContent = scope === 'favorites' ? t('lib.fav_empty')
                : scope === 'recent' ? t('lib.recent_empty')
                : scope === 'custom' ? t('lib.custom_empty')
                : t('lib.empty');
            grid.appendChild(empty);
            if (keepScroll) grid.scrollTop = top;
            return;
        }
        list.forEach(meta => {
            const ids = instsOf(meta.script);
            const card = document.createElement('div');
            card.className = `ind-lib-card${ids.length ? ' on' : ''}`;
            card.dataset.script = meta.script;
            const main = document.createElement('div');
            main.className = 'ind-lib-card-main';
            const isZh = lang() === 'zh';
            const primary = isZh ? (meta.title_zh || meta.title) : (meta.title || meta.title_zh);
            const secondary = isZh
                ? (meta.short === meta.title ? '' : `${meta.short} · ${meta.title}`)
                : (meta.short !== meta.title ? meta.short : '');
            card.title = [primary, meta.script, isZh ? meta.desc : ''].filter(Boolean).join('\n');
            const zh = document.createElement('div');
            zh.className = 'ind-lib-zh';
            zh.textContent = primary;
            main.appendChild(zh);
            if (secondary) {
                const en = document.createElement('div');
                en.className = 'ind-lib-en';
                en.textContent = secondary;
                main.appendChild(en);
            }
            card.appendChild(main);
            // v0.5.4：收藏星标（独立于「已添加」；点星只切换收藏，不加实例）
            const fav = isFavorite(meta.script);
            const star = document.createElement('button');
            star.className = `ind-lib-fav${fav ? ' on' : ''}`;
            star.type = 'button';
            star.textContent = fav ? '★' : '☆';
            star.title = fav ? t('lib.fav_remove') : t('lib.fav_add');
            star.setAttribute('aria-pressed', fav ? 'true' : 'false');
            star.onclick = (e) => {
                e.stopPropagation();
                const on = toggleFavorite(meta.script);
                // 就地更新星标（不整格重绘）：深层滚动位置不跳回顶部
                star.classList.toggle('on', on);
                star.textContent = on ? '★' : '☆';
                star.title = on ? t('lib.fav_remove') : t('lib.fav_add');
                star.setAttribute('aria-pressed', on ? 'true' : 'false');
                renderNav();
                if (_nav === 'favorites') renderGrid(true);   // 取消收藏后卡片应消失
            };
            card.appendChild(star);
            if (meta.source === 'custom') {
                const src = document.createElement('span');
                src.className = 'ind-lib-src';
                src.textContent = t('lib.custom_badge');
                src.title = meta.shadowed ? t('lib.shadow_hint') : t('lib.custom_hint');
                card.appendChild(src);
            }
            if (ids.length) {
                const badge = document.createElement('span');
                badge.className = 'ind-lib-badge';
                badge.textContent = String(ids.length);
                card.appendChild(badge);
                const rm = document.createElement('button');
                rm.className = 'ind-lib-rm';
                rm.textContent = '×';
                rm.title = t('lib.remove_all');
                rm.onclick = async (e) => {
                    e.stopPropagation();
                    await removeAll(meta);
                    renderNav(); renderGrid(true);
                    if (_onChange) _onChange();
                };
                card.appendChild(rm);
            }
            card.onclick = async () => {
                if (await addOne(meta)) {
                    renderNav(); renderGrid(true);
                    // 重绘后在新节点上放 pop 动画（旧卡已丢弃，动画才看得见）
                    const fresh = grid.querySelector(`.ind-lib-card[data-script="${CSS.escape(meta.script)}"]`);
                    if (fresh) {
                        fresh.classList.add('just-added');
                        setTimeout(() => fresh.classList.remove('just-added'), 450);
                    }
                    if (_onChange) _onChange();
                }
            };
            grid.appendChild(card);
        });
        if (keepScroll) grid.scrollTop = top;
    }

    renderNav(); renderGrid();
    document.body.appendChild(modal);
    setTimeout(() => search.focus(), 0);
}
