/* Moz DXF/DWG Viewer —— Webview 逻辑：把后端的**图元 JSON**（可交互的原始图纸）画到
   <canvas> 上：图层开关、悬停显示图元信息、点选高亮、滚轮缩放（光标锚点）、拖动平移、
   双击还原。不加载任何远程内容（CSP 由扩展页头限制）。 */
(function () {
  'use strict';

  // @ts-ignore —— vscode 注入
  const vscode = acquireVsCodeApi();

  const canvas = document.getElementById('canvas');
  const ctx = canvas.getContext('2d');
  const layersBox = document.getElementById('layers');
  const layersList = document.getElementById('layers-list');
  const tooltip = document.getElementById('tooltip');
  const statusEl = document.getElementById('status');
  const errorBox = document.getElementById('error');
  const hint = document.getElementById('hint');

  const state = {
    model: null,          // {layers:[], items:[...]}
    visible: new Set(),   // 可见图层
    scale: 1,
    tx: 0,
    ty: 0,
    hover: -1,
    sel: -1,
    drag: null,
    drawing: false,
  };

  function dpr() {
    return window.devicePixelRatio || 1;
  }

  function resize() {
    canvas.width = Math.round(canvas.clientWidth * dpr());
    canvas.height = Math.round(canvas.clientHeight * dpr());
    invalidate();
  }
  window.addEventListener('resize', resize);

  /* 视图变换：世界 y 向上 → 屏幕 y 向下；顶点：sx = tx + x*s，sy = ty − y*s */
  function screenToWorld(sx, sy) {
    return { x: (sx - state.tx) / state.scale, y: (state.ty - sy) / state.scale };
  }

  function fit() {
    const model = state.model;
    if (!model || !model.items.length) {
      return;
    }
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const item of model.items) {
      const points = item.points;
      if (!points) {
        continue;
      }
      for (let i = 0; i < points.length; i += 2) {
        const x = points[i];
        const y = points[i + 1];
        if (x < x0) { x0 = x; }
        if (x > x1) { x1 = x; }
        if (y < y0) { y0 = y; }
        if (y > y1) { y1 = y; }
      }
    }
    if (!(x1 > x0) || !(y1 > y0)) {
      return;
    }
    const s = Math.min(canvas.clientWidth / (x1 - x0), canvas.clientHeight / (y1 - y0)) * 0.96;
    state.scale = s;
    state.tx = (canvas.clientWidth - (x1 - x0) * s) / 2 - x0 * s;
    state.ty = (canvas.clientHeight + (y1 - y0) * s) / 2 + y0 * s;
    invalidate();
  }

  function invalidate() {
    if (!state.drawing) {
      state.drawing = true;
      requestAnimationFrame(draw);
    }
  }

  function draw() {
    state.drawing = false;
    ctx.setTransform(dpr(), 0, 0, dpr(), 0, 0);
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    const model = state.model;
    if (!model) {
      return;
    }
    // 世界 → 屏幕（y 翻转）；线宽 = 1 设备像素
    ctx.setTransform(dpr() * state.scale, 0, 0, -dpr() * state.scale,
                     dpr() * state.tx, dpr() * state.ty);
    ctx.lineWidth = 1 / state.scale;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    for (let i = 0; i < model.items.length; i++) {
      const item = model.items[i];
      if (!state.visible.has(item.layer)) {
        continue;
      }
      if (item.text) {
        drawText(item);
        continue;
      }
      const points = item.points;
      if (!points || points.length < 2) {
        continue;
      }
      ctx.strokeStyle = item.color;
      ctx.fillStyle = item.color;
      ctx.setLineDash(item.dash || []);
      ctx.beginPath();
      ctx.moveTo(points[0], points[1]);
      for (let j = 2; j < points.length; j += 2) {
        ctx.lineTo(points[j], points[j + 1]);
      }
      if (item.closed || item.fill) {
        ctx.closePath();
      }
      if (item.fill) {
        ctx.fill();
      } else {
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);
    if (state.hover >= 0 && state.hover !== state.sel) {
      highlight(state.hover, true);
    }
    if (state.sel >= 0) {
      highlight(state.sel, false);
    }
  }

  function drawText(item) {
    ctx.save();
    ctx.translate(item.pos[0], item.pos[1]);
    ctx.rotate(item.rot || 0);
    ctx.font = Math.max(item.h || 2.5, 1 / state.scale) + 'px sans-serif';
    ctx.fillStyle = item.color;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(item.text, 0, 0);
    ctx.restore();
  }

  function highlight(index, faint) {
    const item = state.model.items[index];
    const points = item.points;
    if (!points || points.length < 2) {
      return;
    }
    ctx.save();
    ctx.strokeStyle = faint ? 'rgba(0,160,255,0.6)' : '#e06c00';
    ctx.lineWidth = (faint ? 4 : 6) / state.scale;
    ctx.beginPath();
    ctx.moveTo(points[0], points[1]);
    for (let j = 2; j < points.length; j += 2) {
      ctx.lineTo(points[j], points[j + 1]);
    }
    if (item.closed) {
      ctx.closePath();
    }
    ctx.stroke();
    ctx.restore();
  }

  /* ---- 命中测试 ---- */
  function hitTest(world) {
    const model = state.model;
    const toleranceSquared = Math.pow(8 / state.scale, 2);   // 8 设备像素
    let best = -1;
    let bestD = toleranceSquared;
    for (let i = 0; i < model.items.length; i++) {
      const item = model.items[i];
      if (!state.visible.has(item.layer)) {
        continue;
      }
      const d = distanceToItem(item, world);
      if (d !== null && d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return best;
  }

  function distanceToItem(item, p) {
    if (item.text && item.pos) {
      const dx = item.pos[0] - p.x;
      const dy = item.pos[1] - p.y;
      return dx * dx + dy * dy;
    }
    const points = item.points;
    if (!points || points.length < 4) {
      return null;
    }
    let best = Infinity;
    for (let j = 0; j + 3 < points.length; j += 2) {
      best = Math.min(best, distToSegment(p, points, j));
    }
    if (item.closed) {
      best = Math.min(best, distToSegment(p, points, points.length - 4));
    }
    return best;
  }

  function distToSegment(p, points, j) {
    const x1 = points[j];
    const y1 = points[j + 1];
    const x2 = points[j + 2];
    const y2 = points[j + 3];
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lengthSquared = dx * dx + dy * dy;
    let t = lengthSquared ? ((p.x - x1) * dx + (p.y - y1) * dy) / lengthSquared : 0;
    t = Math.max(0, Math.min(1, t));
    const qx = x1 + t * dx;
    const qy = y1 + t * dy;
    const ex = p.x - qx;
    const ey = p.y - qy;
    return ex * ex + ey * ey;
  }

  function eventWorld(event) {
    const rect = canvas.getBoundingClientRect();
    return screenToWorld(event.clientX - rect.left, event.clientY - rect.top);
  }

  /* ---- 交互 ---- */
  canvas.addEventListener('wheel', function (event) {
    event.preventDefault();
    const wx = eventWorld(event).x;
    const wy = eventWorld(event).y;
    const rect = canvas.getBoundingClientRect();
    const sx = event.clientX - rect.left;
    const sy = event.clientY - rect.top;
    const factor = event.deltaY < 0 ? 1.18 : 1 / 1.18;
    const next = Math.min(256, Math.max(0.01, state.scale * factor));
    state.scale = next;
    state.tx = sx - wx * next;
    state.ty = sy + wy * next;
    invalidate();
  }, { passive: false });

  canvas.addEventListener('pointerdown', function (event) {
    if (event.button !== 0) {
      return;
    }
    state.drag = { x: event.clientX, y: event.clientY };
    canvas.setPointerCapture(event.pointerId);
    canvas.classList.add('dragging');
    event.preventDefault();
  });

  canvas.addEventListener('pointermove', function (event) {
    if (state.drag) {
      state.tx += event.clientX - state.drag.x;
      state.ty += event.clientY - state.drag.y;
      state.drag = { x: event.clientX, y: event.clientY };
      invalidate();
      return;
    }
    const hit = hitTest(eventWorld(event));
    state.hover = hit;
    if (hit >= 0 && state.model) {
      const item = state.model.items[hit];
      tooltip.style.display = 'block';
      tooltip.style.left = event.clientX + 12 + 'px';
      tooltip.style.top = event.clientY + 12 + 'px';
      tooltip.textContent = item.kind + ' · 图层 ' + item.layer;
    } else {
      tooltip.style.display = 'none';
    }
    invalidate();
  });

  function endDrag(event) {
    if (!state.drag) {
      return;
    }
    state.drag = null;
    canvas.classList.remove('dragging');
    if (event && typeof event.releasePointerCapture === 'function') {
      event.releasePointerCapture(event.pointerId);
    }
  }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);

  canvas.addEventListener('click', function (event) {
    const hit = hitTest(eventWorld(event));
    state.sel = hit;
    const item = hit >= 0 && state.model ? state.model.items[hit] : null;
    statusEl.textContent = item
      ? '选中：' + item.kind + ' · ' + item.layer +
        (item.text ? ' · ' + item.text : '') +
        (item.points ? ' · ' + item.points.length / 2 + ' 点' : '')
      : '未选中';
    invalidate();
  });

  canvas.addEventListener('dblclick', fit);

  /* ---- 图层开关 ---- */
  function buildLayers() {
    layersList.innerHTML = '';
    for (const name of state.model.layers) {
      state.visible.add(name);
      const label = document.createElement('label');
      label.className = 'layer-row';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.checked = true;
      check.dataset.layer = name;
      check.addEventListener('change', function () {
        if (check.checked) {
          state.visible.add(name);
        } else {
          state.visible.delete(name);
        }
        invalidate();
      });
      label.appendChild(check);
      const span = document.createElement('span');
      span.textContent = name;
      label.appendChild(span);
      layersList.appendChild(label);
    }
  }

  document.getElementById('layers-all').addEventListener('click', function () {
    for (const name of state.model.layers) {
      state.visible.add(name);
    }
    for (const check of layersList.querySelectorAll('input')) {
      check.checked = true;
    }
    invalidate();
  });
  document.getElementById('layers-none').addEventListener('click', function () {
    state.visible.clear();
    for (const check of layersList.querySelectorAll('input')) {
      check.checked = false;
    }
    invalidate();
  });

  /* ---- 消息 ---- */
  function showModel(model, name) {
    errorBox.hidden = true;
    state.model = model;
    state.hover = -1;
    state.sel = -1;
    statusEl.textContent = name + ' · ' + model.items.length + ' 个图元';
    hint.textContent = '滚轮缩放 · 拖动平移 · 双击还原 · 悬停看图层/点选看详情';
    buildLayers();
    requestAnimationFrame(fit);
  }

  function showError(message) {
    state.model = null;
    layersList.innerHTML = '';
    statusEl.textContent = '';
    tooltip.style.display = 'none';
    errorBox.hidden = false;
    errorBox.textContent = message;
  }

  window.addEventListener('message', function (event) {
    const message = event.data;
    if (message.type === 'model') {
      try {
        showModel(JSON.parse(message.json), message.name);
      } catch (error) {
        showError('后端返回的模型 JSON 解析失败：\n' + String(error));
      }
    } else if (message.type === 'error') {
      showError(message.error);
    }
  });

  resize();
})();