// draw_interact.js —— v0.5 桩+桥：0.4 自绘交互层退役（Vela 原生接管），侧栏按钮改接 adapter 工具桥。
import { setDrawToolCore } from './vela_adapter.js';
export function setDrawTool(tool) { setDrawToolCore(tool); }
export function cancelDrawing() { setDrawToolCore(null); }
export function initDrawToolbar() {
    document.querySelectorAll('#draw-toolbar .draw-tool').forEach(el => {
        el.onclick = () => setDrawToolCore(el.dataset.tool);
    });
}
export function attachDrawingInteraction() {}
