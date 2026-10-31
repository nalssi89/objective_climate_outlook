/* 의존성 없는 SVG 차트: 앙상블 플룸 시계열, 기간별 멤버 분포 */
(function (global) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceTicks(lo, hi, n = 5) {
    const span = hi - lo || 1;
    const step0 = span / n;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function extent(arrs) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrs) for (const v of a || []) if (v != null && isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    return [lo, hi];
  }
  function tooltip(container) {
    let t = container.querySelector('.ctip');
    if (!t) {
      t = document.createElement('div');
      t.className = 'ctip';
      t.hidden = true;
      container.appendChild(t);
    }
    return t;
  }

  /**
   * 앙상블 플룸
   * opt: {dates, bands:[{lo,hi,color,opacity,label}], lines:[{v,color,width,dash,label}], periods:[{start,end,label}],
   *       unit, digits, zeroBase, rows:(i)=>[[label, value, color]]}
   */
  function plume(container, opt) {
    container.innerHTML = '';
    container.style.position = 'relative';
    const W = Math.max(container.clientWidth, 320), H = opt.height || 280;
    const m = { l: 44, r: 12, t: 22, b: 30 };
    const svg = el('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'svgchart', role: 'img', 'aria-label': opt.aria || '' }, container);
    const n = opt.dates.length;
    let [lo, hi] = extent([...opt.bands.flatMap((b) => [b.lo, b.hi]), ...opt.lines.map((l) => l.v)]);
    if (opt.zeroBase) lo = Math.min(0, lo);
    const pad = (hi - lo) * 0.06 || 1;
    lo -= opt.zeroBase ? 0 : pad;
    hi += pad;
    const x = (i) => m.l + ((i + 0.5) / n) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
    const g = el('g', {}, svg);

    // 예측 기간 구분
    const idx = Object.fromEntries(opt.dates.map((d, i) => [d, i]));
    (opt.periods || []).forEach((p, k) => {
      const i0 = idx[p.start], i1 = idx[p.end];
      if (i0 == null || i1 == null) return;
      const x0 = x(i0) - (x(1) - x(0)) / 2, x1 = x(i1) + (x(1) - x(0)) / 2;
      if (k % 2 === 0) el('rect', { x: x0, y: m.t, width: x1 - x0, height: H - m.t - m.b, class: 'pband' }, g);
      const t = el('text', { x: (x0 + x1) / 2, y: m.t - 7, class: 'plabel', 'text-anchor': 'middle' }, g);
      t.textContent = p.label;
    });
    // 격자
    for (const v of niceTicks(lo, hi, 5)) {
      el('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: 'grid' }, g);
      const t = el('text', { x: m.l - 6, y: y(v) + 4, class: 'tick', 'text-anchor': 'end' }, g);
      t.textContent = Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : +v.toFixed(2);
    }
    const every = Math.ceil(n / Math.max(4, Math.floor((W - 60) / 60)));
    opt.dates.forEach((d, i) => {
      const dt = new Date(d + 'T00:00:00');
      if (n > 50 ? dt.getDate() === 1 : i % every === 0) {
        const t = el('text', { x: x(i), y: H - m.b + 16, class: 'tick', 'text-anchor': 'middle' }, g);
        t.textContent = `${dt.getMonth() + 1}/${dt.getDate()}`;
        el('line', { x1: x(i), x2: x(i), y1: H - m.b, y2: H - m.b + 4, class: 'axis' }, g);
      }
    });
    el('line', { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, class: 'axis' }, g);
    if (opt.unit) {
      const t = el('text', { x: 4, y: 12, class: 'tick unit' }, g);
      t.textContent = opt.unit;
    }

    // 밴드
    for (const b of opt.bands) {
      let d = '';
      const ok = (i) => b.lo[i] != null && b.hi[i] != null;
      for (let i = 0; i < n; i++) if (ok(i)) d += (d ? 'L' : 'M') + x(i) + ',' + y(b.hi[i]);
      for (let i = n - 1; i >= 0; i--) if (ok(i)) d += 'L' + x(i) + ',' + y(b.lo[i]);
      if (d) el('path', { d: d + 'Z', fill: b.color, 'fill-opacity': b.opacity, stroke: 'none' }, g);
    }
    // 선
    for (const l of opt.lines) {
      let d = '';
      let pen = false;
      for (let i = 0; i < n; i++) {
        if (l.v[i] == null) { pen = false; continue; }
        d += (pen ? 'L' : 'M') + x(i) + ',' + y(l.v[i]);
        pen = true;
      }
      el('path', { d, fill: 'none', stroke: l.color, 'stroke-width': l.width || 2, 'stroke-dasharray': l.dash, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, g);
    }

    // 크로스헤어 + 툴팁
    const cross = el('line', { y1: m.t, y2: H - m.b, class: 'cross', visibility: 'hidden' }, svg);
    const dots = opt.lines.map((l) => el('circle', { r: 4, fill: l.color, stroke: 'var(--surface)', 'stroke-width': 2, visibility: 'hidden' }, svg));
    const tip = tooltip(container);
    const hit = el('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg);
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ev.clientX - r.left;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * n - 0.5)));
      cross.setAttribute('x1', x(i));
      cross.setAttribute('x2', x(i));
      cross.setAttribute('visibility', 'visible');
      opt.lines.forEach((l, k) => {
        if (l.v[i] == null) return dots[k].setAttribute('visibility', 'hidden');
        dots[k].setAttribute('cx', x(i));
        dots[k].setAttribute('cy', y(l.v[i]));
        dots[k].setAttribute('visibility', 'visible');
      });
      const d = opt.dates[i];
      tip.innerHTML = `<div class="th">${d} (${'일월화수목금토'[new Date(d + 'T00:00:00').getDay()]})</div>` +
        opt.rows(i).map(([lab, v, c]) => `<div class="tr">${c ? `<i style="background:${c}"></i>` : '<i></i>'}<span>${lab}</span><b>${v}</b></div>`).join('');
      tip.hidden = false;
      const tw = tip.offsetWidth;
      tip.style.left = (x(i) + 14 + tw > W ? x(i) - tw - 14 : x(i) + 14) + 'px';
      tip.style.top = m.t + 4 + 'px';
    };
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerleave', () => {
      tip.hidden = true;
      cross.setAttribute('visibility', 'hidden');
      dots.forEach((d) => d.setAttribute('visibility', 'hidden'));
    });
  }

  /**
   * 기간별 멤버 분포 (가로 행)
   * rows: [{label, sub, members, q:[p10,p25,p50,p75,p90], bounds:[b10,b33,b50,b67,b90], mean, clim}]
   */
  function distribution(container, rows, opt) {
    container.innerHTML = '';
    container.style.position = 'relative';
    const W = Math.max(container.clientWidth, 320);
    const rh = 46, m = { l: 92, r: 16, t: 8, b: 28 };
    const H = m.t + m.b + rh * rows.length;
    const svg = el('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'svgchart' }, container);
    const tip = tooltip(container);
    rows.forEach((r, k) => {
      // 행마다 자체 x 척도 (기간 길이에 따라 값 범위가 다름)
      const all = [...(r.members || []), ...r.bounds].filter((v) => v != null && isFinite(v));
      if (!all.length) return;
      let lo = Math.min(...all), hi = Math.max(...all);
      const pad = (hi - lo) * 0.08 || 1;
      lo = opt.zeroBase ? Math.max(0, lo - pad) : lo - pad;
      hi += pad;
      const x = (v) => m.l + ((v - lo) / (hi - lo)) * (W - m.l - m.r);
      const y0 = m.t + k * rh, yc = y0 + rh / 2 - 4;
      const g = el('g', {}, svg);
      const [b10, b33, , b67, b90] = r.bounds;
      const zone = (a, b, c, op) => el('rect', { x: x(a), y: y0 + 4, width: Math.max(0, x(b) - x(a)), height: rh - 16, fill: c, 'fill-opacity': op, rx: 3 }, g);
      zone(lo, b33, opt.low, 0.22);
      zone(b33, b67, opt.near, 0.22);
      zone(b67, hi, opt.high, 0.22);
      zone(lo, b10, opt.low, 0.18);
      zone(b90, hi, opt.high, 0.18);
      const lab = el('text', { x: 6, y: yc + 1, class: 'rlabel' }, g);
      lab.textContent = r.label;
      const sub = el('text', { x: 6, y: yc + 14, class: 'tick' }, g);
      sub.textContent = r.sub || '';
      // 상자
      if (r.q[1] != null) el('rect', { x: x(r.q[1]), y: yc - 8, width: Math.max(1, x(r.q[3]) - x(r.q[1])), height: 16, class: 'box' }, g);
      if (r.q[0] != null) el('line', { x1: x(r.q[0]), x2: x(r.q[4]), y1: yc, y2: yc, class: 'whisk' }, g);
      // 멤버 점 (결정적 지터)
      (r.members || []).forEach((v, j) => {
        if (v == null) return;
        const jy = (((j * 37) % 17) / 16 - 0.5) * 14;
        el('circle', { cx: x(v), cy: yc + jy, r: 2.6, class: 'mdot' }, g);
      });
      if (r.q[2] != null) el('line', { x1: x(r.q[2]), x2: x(r.q[2]), y1: yc - 10, y2: yc + 10, class: 'med' }, g);
      if (r.clim != null) el('line', { x1: x(r.clim), x2: x(r.clim), y1: y0 + 3, y2: y0 + rh - 11, class: 'climline' }, g);
      // 축 눈금(행 하단)
      for (const v of niceTicks(lo, hi, Math.max(3, Math.floor((W - m.l) / 90)))) {
        const t = el('text', { x: x(v), y: y0 + rh + 1, class: 'tick small', 'text-anchor': 'middle' }, g);
        t.textContent = +v.toFixed(2);
      }
      const hit = el('rect', { x: 0, y: y0, width: W, height: rh, fill: 'transparent' }, g);
      hit.addEventListener('pointermove', (ev) => {
        const rr = svg.getBoundingClientRect();
        tip.innerHTML = opt.tip(r);
        tip.hidden = false;
        const px = ev.clientX - rr.left;
        tip.style.left = (px + 14 + tip.offsetWidth > W ? px - tip.offsetWidth - 14 : px + 14) + 'px';
        tip.style.top = y0 + rh - 4 + 'px';
      });
      hit.addEventListener('pointerleave', () => (tip.hidden = true));
    });
    const legend = el('text', { x: m.l, y: H - 6, class: 'tick' }, svg);
    legend.textContent = `세로 실선: 앙상블 중앙값 · 세로 점선: 평년값 · 단위 ${opt.unit}`;
  }

  global.KCO.charts = { plume, distribution };
})(window);
