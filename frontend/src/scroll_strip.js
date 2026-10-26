// ============================================================
// 横向溢出条（v0.6.4 打磨）：画板 / 周期 / 指标 / 结果 共用
// - 单行滚动，隐藏滚动条
// - 左右边缘渐隐（只在真的溢出/可滚时出现）
// - 滚轮纵向手势 → 横向滚动
// - reveal(child)：把激活项滚进可见区
// ============================================================

const BOUND = 'data-xstrip';

export function bindStrip(el) {
    if (!el) return null;
    if (el[BOUND]) return el;
    el[BOUND] = '1';
    el.classList.add('xstrip');

    const update = () => {
        const max = el.scrollWidth - el.clientWidth;
        el.classList.toggle('xstrip-over', max > 2);
        el.classList.toggle('xstrip-left', max > 2 && el.scrollLeft > 2);
        el.classList.toggle('xstrip-right', max > 2 && el.scrollLeft < max - 2);
    };

    el.addEventListener('scroll', update, { passive: true });
    el.addEventListener('wheel', (e) => {
        if (el.scrollWidth <= el.clientWidth + 2) return;
        if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;   // 已经是横向手势
        e.preventDefault();
        el.scrollLeft += e.deltaY;
        update();
    }, { passive: false });

    // 长按拖拽滚动：鼠标/触控笔按住条目左右拖（触摸交给原生滚动）
    // 注意：不用 setPointerCapture —— 捕获会把 click 的 target 改成滚动条本身，
    // 子条目（chip/板/周期）的点击就全丢了；改为拖拽期间挂 document 监听。
    let drag = null;
    let swallowClick = null;

    const onMove = (e) => {
        if (!drag || e.pointerId !== drag.id) return;
        const dx = e.clientX - drag.x;
        if (!drag.moved && Math.abs(dx) > 4) drag.moved = true;
        if (!drag.moved) return;
        e.preventDefault();
        el.scrollLeft = drag.left - dx;
        update();
    };
    const onUp = (e) => {
        if (!drag || (e.pointerId != null && e.pointerId !== drag.id)) return;
        const moved = drag.moved;
        drag = null;
        el.classList.remove('xstrip-drag');
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        document.removeEventListener('pointercancel', onUp);
        if (moved) {
            // 拖完那一下 click 吞掉；只吞这一次，下一个正常点击照常生效
            if (swallowClick) document.removeEventListener('click', swallowClick, true);
            swallowClick = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
            document.addEventListener('click', swallowClick, true);
            setTimeout(() => {
                if (swallowClick) document.removeEventListener('click', swallowClick, true);
                swallowClick = null;
            }, 0);
        }
    };
    el.addEventListener('pointerdown', (e) => {
        if (e.button !== 0 || e.pointerType === 'touch') return;
        if (el.scrollWidth <= el.clientWidth + 2) return;
        drag = { id: e.pointerId, x: e.clientX, left: el.scrollLeft, moved: false };
        el.classList.add('xstrip-drag');
        document.addEventListener('pointermove', onMove, { passive: false });
        document.addEventListener('pointerup', onUp);
        document.addEventListener('pointercancel', onUp);
    });

    el.reveal = (child) => {
        if (!child) return;
        const r = child.getBoundingClientRect();
        const er = el.getBoundingClientRect();
        if (r.left < er.left) el.scrollLeft -= (er.left - r.left + 8);
        else if (r.right > er.right) el.scrollLeft += (r.right - er.right + 8);
        update();
    };

    // 悬停细滚动条（自绘 overlay：不占布局、跨平台一致，只在悬停/拖拽时露出）
    const thumb = document.createElement('div');
    thumb.className = 'xstrip-thumb';
    document.body.appendChild(thumb);
    const updateThumb = () => {
        if (!el.isConnected) { thumb.remove(); return; }
        const max = el.scrollWidth - el.clientWidth;
        const active = el.matches(':hover') || el.classList.contains('xstrip-drag');
        if (max <= 2 || !active) { thumb.style.opacity = '0'; return; }
        const r = el.getBoundingClientRect();
        const w = Math.max(28, r.width * (el.clientWidth / el.scrollWidth));
        const left = r.left + (r.width - w) * (el.scrollLeft / max);
        thumb.style.cssText = `left:${left}px;top:${r.bottom + 1}px;width:${w}px;opacity:1;`;
    };
    el.addEventListener('scroll', updateThumb, { passive: true });
    el.addEventListener('pointerenter', updateThumb);
    el.addEventListener('pointerleave', () => {
        if (!el.classList.contains('xstrip-drag')) thumb.style.opacity = '0';
    });
    el.updateThumb = updateThumb;
    if (window.ResizeObserver) new ResizeObserver(() => { update(); updateThumb(); }).observe(el);
    window.addEventListener('resize', updateThumb);
    requestAnimationFrame(() => { update(); updateThumb(); });
    return el;
}

// 渲染后把当前激活项露出来（结果/画板/周期共用）
export function revealActive(el, selector = '.active') {
    if (!el || !el.reveal) return;
    el.reveal(el.querySelector(selector));
}
