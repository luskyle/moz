/* Moz DXF/DWG Viewer —— Webview 逻辑：渲染后端导出的 SVG，滚轮缩放（以光标为锚点）、
   左键拖动平移、双击还原。不加载任何远程内容（CSP 由扩展页头限制）。 */
(function () {
  'use strict';

  // @ts-ignore —— vscode 注入
  const vscode = acquireVsCodeApi();

  const stage = document.getElementById('stage');
  const art = document.getElementById('art');
  const status = document.getElementById('status');
  const errorBox = document.getElementById('error');
  const hint = document.getElementById('hint');
  let scale = 1;
  let tx = 0;
  let ty = 0;
  let dragging = null; // { x, y } 按下时的光标

  /** 画布居中：把图纸放进视口（留 5% 边距），重置平移与缩放。 */
  function fit() {
    const svg = art.querySelector('svg');
    if (!svg) {
      return;
    }
    const box = svg.getBBox();
    const w = box.width || svg.width.baseVal.value || 1;
    const h = box.height || svg.height.baseVal.value || 1;
    const availW = stage.clientWidth * 0.95;
    const availH = stage.clientHeight * 0.95;
    const s = Math.min(availW / w, availH / h, 1.0);
    scale = s;
    tx = (stage.clientWidth - w * s) / 2 - box.x * s;
    ty = (stage.clientHeight - h * s) / 2 - box.y * s;
    apply();
  }

  function apply() {
    art.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
  }

  function clampZoom(value) {
    return Math.min(64, Math.max(0.02, value));
  }

  /* 滚轮缩放：以光标下的点当锚（图纸上那个点不动） */
  stage.addEventListener('wheel', function (event) {
    event.preventDefault();
    const rect = stage.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    const next = clampZoom(scale * factor);
    tx = px - ((px - tx) * next) / scale;
    ty = py - ((py - ty) * next) / scale;
    scale = next;
    apply();
    status.textContent = Math.round(scale * 100) + '%';
  }, { passive: false });

  stage.addEventListener('pointerdown', function (event) {
    if (event.button !== 0) {
      return;
    }
    dragging = { x: event.clientX, y: event.clientY };
    stage.setPointerCapture(event.pointerId);
    stage.classList.add('dragging');
    event.preventDefault();
  });

  stage.addEventListener('pointermove', function (event) {
    if (!dragging) {
      return;
    }
    tx += event.clientX - dragging.x;
    ty += event.clientY - dragging.y;
    dragging = { x: event.clientX, y: event.clientY };
    apply();
  });

  function endDrag(event) {
    if (!dragging) {
      return;
    }
    dragging = null;
    stage.classList.remove('dragging');
    if (event && typeof event.releasePointerCapture === 'function') {
      event.releasePointerCapture(event.pointerId);
    }
  }

  stage.addEventListener('pointerup', endDrag);
  stage.addEventListener('pointercancel', endDrag);
  stage.addEventListener('dblclick', fit);

  function showSvg(svgText, name) {
    errorBox.hidden = true;
    art.innerHTML = svgText;
    status.textContent = name;
    requestAnimationFrame(fit); // getBBox 要等 SVG 布局完
  }

  function showError(message) {
    art.innerHTML = '';
    status.textContent = '';
    errorBox.hidden = false;
    errorBox.textContent = message;
  }

  window.addEventListener('message', function (event) {
    const message = event.data;
    if (message.type === 'svg') {
      showSvg(message.svg, message.name);
    } else if (message.type === 'error') {
      showError(message.error);
    }
  });

  hint.textContent = '滚轮缩放 · 拖动平移 · 双击还原 · Ctrl+滚轮的图纸用鼠标中键也行';
})();