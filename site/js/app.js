/* 전망 지도 페이지 */
(function () {
  'use strict';
  const K = window.KCO;
  const $ = (id) => document.getElementById(id);

  const state = { issue: 'latest', product: '1m', var: 't2m', period: null, display: 'tercile', thr: null, side: 'high' };
  let manifest, latestManifest, archive, grid, renderer, map, overlay, gridLayer, tileLayer, selMarker;
  const maps = {};
  // 선택한 발표일의 자료 경로 (latest = 최신, 그 밖에는 data/archive/<날짜>/)
  const base = () => (state.issue === 'latest' ? K.DATA : `data/archive/${state.issue}/`);

  // ---------------------------------------------------------------- 초기화
  async function init() {
    initTheme();
    readHash();
    try {
      [manifest, grid] = await Promise.all([K.getJSON(K.DATA + 'manifest.json'), K.getJSON('data/grid.json')]);
    } catch (e) {
      $('issue').textContent = '전망 자료가 없습니다. pipeline/outlook.py 를 실행하세요.';
      console.error(e);
      return;
    }
    const [korea, neighbors] = await Promise.all([K.getJSON('data/geo/korea.geojson'), K.getJSON('data/geo/neighbors.geojson')]);
    renderer = new K.FieldRenderer(grid, korea);
    if (!manifest.products[state.product]) state.product = Object.keys(manifest.products)[0];

    latestManifest = manifest;
    archive = await K.getJSON('data/archive/index.json').catch(() => null);
    if (state.issue !== 'latest') {
      if (archive && archive.issues.some((e) => e.date === state.issue)) {
        manifest = await K.getJSON(base() + 'manifest.json');
      } else {
        state.issue = 'latest';
      }
    }
    buildIssueSelect();
    renderIssueInfo();

    initMap(korea, neighbors);
    buildStaticControls();
    await update();
  }

  // ---------------------------------------------------------------- 발표일 · 갱신 정보
  const KST_MS = 9 * 3600 * 1000;
  const kstParts = (d) => {
    const k = new Date(d.getTime() + KST_MS);
    return { y: k.getUTCFullYear(), m: k.getUTCMonth() + 1, d: k.getUTCDate(), hh: k.getUTCHours(), mm: k.getUTCMinutes() };
  };
  const fmtKST = (d) => {
    const p = kstParts(d);
    return `${p.y}.${p.m}.${p.d} ${String(p.hh).padStart(2, '0')}:${String(p.mm).padStart(2, '0')} KST`;
  };
  // 정기 갱신: 매일 07:10 KST (GitHub Actions 22:10 UTC)
  function nextUpdate(now = new Date()) {
    const t = new Date(now);
    t.setUTCHours(22, 10, 0, 0);
    if (t <= now) t.setUTCDate(t.getUTCDate() + 1);
    return t;
  }

  function renderIssueInfo() {
    const issued = new Date(manifest.issued);
    const latest = new Date(latestManifest.issued);
    const ageH = (Date.now() - latest.getTime()) / 3600e3;
    const nu = kstParts(nextUpdate());
    let html = `<b>발표</b> ${fmtKST(issued)}` +
      (manifest.demo ? ' <span class="badge warn">DEMO 합성자료</span>' : ' <span class="badge">Open-Meteo 실자료</span>');
    if (state.issue !== 'latest') html += ' <span class="badge warn">지난 발표</span>';
    else if (!latestManifest.demo && ageH > 30) html += ` <span class="badge warn" title="정기 갱신이 늦어지고 있습니다">갱신 지연 ${Math.floor(ageH)}시간</span>`;
    $('issue').innerHTML = html;
    $('demoRibbon').hidden = !manifest.demo;
    $('updateHint').textContent = `1개월(EC46)은 매일, 3개월(SEAS5)은 매월 5일 모델이 갱신됩니다. 다음 정기 갱신 ${nu.m}/${nu.d} 07:10 KST.`;
  }

  function buildIssueSelect() {
    const sel = $('issueSel');
    const latestDay = latestManifest.issued.slice(0, 10);
    const opts = [['latest', `최신 · ${latestDay}`]];
    for (const e of (archive && archive.issues) || []) if (e.date !== latestDay) opts.push([e.date, e.date]);
    sel.innerHTML = opts.map(([v, l]) => `<option value="${v}" ${v === state.issue ? 'selected' : ''}>${l}</option>`).join('');
    sel.disabled = opts.length < 2;
    sel.onchange = async () => {
      state.issue = sel.value;
      manifest = state.issue === 'latest' ? latestManifest : await K.getJSON(base() + 'manifest.json');
      renderIssueInfo();
      await update();
    };
  }

  function initTheme() {
    const saved = (() => { try { return localStorage.getItem('kco-theme'); } catch (e) { return null; } })();
    if (saved) document.documentElement.dataset.theme = saved;
    $('themeBtn').onclick = () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === 'dark'
        : matchMedia('(prefers-color-scheme: dark)').matches;
      const next = dark ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('kco-theme', next); } catch (e) { /* 무시 */ }
    };
  }

  function readHash() {
    const h = new URLSearchParams(location.hash.slice(1));
    for (const k of ['issue', 'product', 'var', 'period', 'display', 'thr', 'side']) if (h.get(k)) state[k] = h.get(k);
  }
  function writeHash() {
    const h = new URLSearchParams();
    if (state.issue !== 'latest') h.set('issue', state.issue);
    for (const k of ['product', 'var', 'period', 'display']) h.set(k, state[k]);
    if (state.display === 'threshold') h.set('thr', state.thr);
    if (state.display === 'extreme') h.set('side', state.side);
    history.replaceState(null, '', '#' + h.toString());
  }

  // ---------------------------------------------------------------- 지도
  function initMap(korea, neighbors) {
    map = L.map('map', { zoomControl: true, minZoom: 5, maxZoom: 10, zoomSnap: 0.25, attributionControl: true });
    map.attributionControl.setPrefix(false);
    map.createPane('land').style.zIndex = 200;
    map.createPane('field').style.zIndex = 300;
    map.createPane('lines').style.zIndex = 420;
    map.createPane('labels').style.zIndex = 450;
    L.geoJSON(neighbors, { pane: 'land', interactive: false, style: { className: 'nb-land', weight: 0.6 } }).addTo(map);
    L.geoJSON(korea, { pane: 'land', interactive: false, style: { className: 'kr-land', weight: 0 } }).addTo(map);
    L.geoJSON(korea, { pane: 'lines', interactive: false, style: { className: 'kr-line', weight: 0.9, fill: false } }).addTo(map);
    map.fitBounds([[33.1, 124.3], [43.0, 131.0]]);
    map.setMaxBounds([[28, 115], [48, 140]]);

    for (const [name, la, lo] of K.CITIES) {
      L.marker([la, lo], {
        pane: 'labels',
        icon: L.divIcon({ className: 'city', html: `<i></i><span>${name}</span>`, iconSize: [8, 8], iconAnchor: [4, 4] }),
        keyboard: false,
      }).on('click', () => openPoint(la, lo)).addTo(map);
      const o = document.createElement('option');
      o.value = `${la},${lo}`;
      o.textContent = name;
      $('citySel').appendChild(o);
    }
    gridLayer = L.layerGroup(grid.points.map((p) => L.circleMarker(p, { pane: 'labels', radius: 2, className: 'gridpt', interactive: false })));
    tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 10, opacity: 0.55, attribution: '© OpenStreetMap contributors',
    });

    map.on('mousemove', onHover);
    map.on('mouseout', () => ($('hoverBox').hidden = true));
    map.on('click', (e) => {
      if (renderer.isLand(e.latlng.lat, e.latlng.lng) || K.nearestPoint(grid, e.latlng.lat, e.latlng.lng).dist < 0.3) {
        openPoint(e.latlng.lat, e.latlng.lng);
      }
    });
    $('citySel').onchange = (e) => {
      if (!e.target.value) return;
      const [la, lo] = e.target.value.split(',').map(Number);
      map.setView([la, lo], Math.max(map.getZoom(), 7));
      openPoint(la, lo);
    };
    $('gridChk').onchange = (e) => (e.target.checked ? gridLayer.addTo(map) : gridLayer.remove());
    $('tileChk').onchange = (e) => {
      document.body.classList.toggle('tiles', e.target.checked);
      e.target.checked ? tileLayer.addTo(map) : tileLayer.remove();
    };
  }

  // ---------------------------------------------------------------- 컨트롤
  function seg(el, items, cur, onPick) {
    el.innerHTML = '';
    for (const [val, label, title] of items) {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', String(val === cur));
      b.className = val === cur ? 'on' : '';
      b.innerHTML = label;
      if (title) b.title = title;
      b.onclick = () => onPick(val);
      el.appendChild(b);
    }
  }

  function buildStaticControls() {
    $('closeBtn').onclick = () => ($('pointWin').hidden = true);
    $('popoutBtn').onclick = () => {
      const src = $('pointFrame').getAttribute('src');
      if (src) window.open(src.replace('&embed=1', ''), 'kco_point', 'width=1040,height=900');
    };
    makeDraggable($('pointWin'), $('pointWinBar'));
  }

  function buildControls() {
    const P = manifest.products[state.product];
    seg($('productSeg'), Object.entries(manifest.products).map(([k, p]) => [k, `<b>${p.name}</b><small>${k === '1m' ? '주별 · 4주' : '월별 · 3개월'}</small>`]),
      state.product, (v) => { state.product = v; state.period = null; update(); });
    $('modelHint').textContent = `${P.model} · ${K.fmtDate(P.periods[0].start)}–${K.fmtDate(P.periods[P.periods.length - 1].end)}`;

    seg($('varSeg'), Object.keys(manifest.variables).map((k) => [k, `<span aria-hidden="true">${K.VAR_META[k].icon}</span>${K.VAR_META[k].short}`]),
      state.var, (v) => { state.var = v; state.thr = null; update(); });

    seg($('periodChips'), P.periods.map((p) => [p.id, `<b>${p.label}</b><small>${K.fmtDate(p.start)}–${K.fmtDate(p.end)}</small>`]),
      state.period, (v) => { state.period = v; update(); });

    const V = manifest.variables[state.var];
    const disp = Object.entries(K.PRODUCTS).map(([k, d]) => [k, k === 'anom' && V.mode === 'mul' ? '평년비 (%)' : d.name]);
    seg($('displayList'), disp, state.display, (v) => { state.display = v; update(); });

    // 임계값
    const f = currentField();
    const keys = Object.keys(f.thr);
    if (!keys.includes(state.thr)) state.thr = keys.find((k) => /gt/.test(k)) || keys[0];
    $('thresholdBox').hidden = state.display !== 'threshold';
    const sel = $('thresholdSel');
    sel.innerHTML = keys.map((k) => `<option value="${k}" ${k === state.thr ? 'selected' : ''}>${K.thresholdLabel(k, V)}</option>`).join('');
    sel.onchange = () => { state.thr = sel.value; update(); };
    $('extremeBox').hidden = state.display !== 'extreme';
    seg($('extremeSeg'), [['high', `상위 10% (매우 ${K.POLES[state.var].highName})`], ['low', `하위 10% (매우 ${K.POLES[state.var].lowName})`]],
      state.side, (v) => { state.side = v; update(); });
  }

  function currentField(pid = state.period) {
    return maps[base() + state.product].fields[state.var][pid];
  }

  // 표출 항목 → [레이어 배열], 색 함수, 범례
  function spec(f, period) {
    const V = manifest.variables[state.var];
    const vk = state.var;
    const opts = { kind: period.kind, unit: V.unit };
    switch (state.display) {
      case 'tercile':
        return { layers: [f.below, f.near, f.above], color: (b, n, a) => K.tercileColor(vk, b, n, a), legend: 'tercile' };
      case 'median': {
        const s = K.scaleFor('median', vk);
        return { layers: [f.gt_median], color: (v) => K.colorOf(s, v), scale: s, unit: '%' };
      }
      case 'mean': {
        const s = K.scaleFor('mean', vk, opts);
        return { layers: [f.mean], color: (v) => K.colorOf(s, v), scale: s, unit: s.unit };
      }
      case 'anom': {
        const s = K.scaleFor('anom', vk, opts);
        return { layers: [V.mode === 'add' ? f.anom : f.anom_pct], color: (v) => K.colorOf(s, v), scale: s, unit: s.unit };
      }
      case 'threshold': {
        const s = K.scaleFor('threshold', vk, { side: K.thresholdSide(state.thr) });
        return { layers: [f.thr[state.thr] || []], color: (v) => K.colorOf(s, v), scale: s, unit: '%' };
      }
      case 'extreme': {
        const s = K.scaleFor('extreme', vk, { side: state.side });
        return { layers: [state.side === 'high' ? f.gt_p90 : f.lt_p10], color: (v) => K.colorOf(s, v), scale: s, unit: '%' };
      }
      case 'spread': {
        const s = K.scaleFor('spread', vk, opts);
        return { layers: [f.spread], color: (v) => K.colorOf(s, v), scale: s, unit: V.unit };
      }
    }
  }

  // ---------------------------------------------------------------- 갱신
  async function update() {
    if (!manifest.products[state.product]) state.product = Object.keys(manifest.products)[0];
    const mk = base() + state.product;
    if (!maps[mk]) maps[mk] = await K.getJSON(base() + `map_${state.product}.json`);
    const P = manifest.products[state.product];
    if (!P.periods.find((p) => p.id === state.period)) state.period = P.periods[0].id;
    if (!manifest.variables[state.var]) state.var = 't2m';
    if (!K.PRODUCTS[state.display]) state.display = 'tercile';
    buildControls();
    writeHash();

    const period = P.periods.find((p) => p.id === state.period);
    const f = currentField();
    const sp = spec(f, period);
    const canvas = renderer.render(sp.layers, sp.color, 560);
    if (overlay) overlay.setUrl(canvas.toDataURL());
    else overlay = L.imageOverlay(canvas.toDataURL(), renderer.bounds, { pane: 'field', interactive: false, className: 'fieldimg' }).addTo(map);
    state.spec = sp;

    const V = manifest.variables[state.var];
    const dname = state.display === 'anom' && V.mode === 'mul' ? '평년비' : K.PRODUCTS[state.display].name;
    const extra = state.display === 'threshold' ? ` · ${K.thresholdLabel(state.thr, V)}` :
      state.display === 'extreme' ? ` · ${state.side === 'high' ? '상위' : '하위'} 10%` : '';
    $('mapTitle').textContent = `${V.name} · ${dname}${extra}`;
    $('mapSub').textContent = (state.issue === 'latest' ? '' : `[지난 발표 ${state.issue}] `) +
      `${P.name} ${period.label} (${period.start} ~ ${period.end}) · ${P.model}`;
    $('explain').textContent = K.PRODUCTS[state.display].desc + (state.display === 'mean' || state.display === 'anom'
      ? ` 단위: ${V.agg === 'sum' ? '기간 누적' : '기간 평균'} ${V.unit}.` : '');
    renderLegend(sp);
    renderThumbs();
    // 열려 있는 지점 창도 같은 전망·요소로 동기화
    if (!$('pointWin').hidden && state.openIdx != null) setFrame(state.openIdx);
  }

  function renderLegend(sp) {
    const el = $('legend');
    const P = K.POLES[state.var];
    if (sp.legend === 'tercile') {
      const lv = ['40', '50', '60', '70+'];
      const row = (name, cols) => `<div class="lrow"><span class="lname">${name}</span>${cols.map((c, i) => `<span class="sw" style="background:${c}" title="${lv[i]}%"></span>`).join('')}</div>`;
      el.innerHTML = `<div class="tlegend">
        ${row(P.highName, [1, 2, 3, 4].map((i) => P.high[i]))}
        ${row('비슷', ['#d9d8d3', '#c3c2b7', '#a9a7a0', '#898781'])}
        ${row(P.lowName, [3, 2, 1, 0].map((i) => P.low[i]))}
        <div class="lrow ticks"><span class="lname"></span>${lv.map((l) => `<span>${l}</span>`).join('')}</div>
        <div class="lnote"><span class="sw" style="background:#f4f3f0"></span> 모든 범주 40% 미만(불확실)</div></div>`;
      return;
    }
    const s = sp.scale;
    const lab = s.breaks.map((b) => (Math.abs(b) >= 100 || Number.isInteger(b) ? b : b.toFixed(b % 0.5 ? 2 : 1)));
    el.innerHTML = `<div class="slegend"><div class="bar">${s.colors.map((c) => `<span style="background:${c}"></span>`).join('')}</div>
      <div class="ticks">${lab.map((l) => `<span>${l}</span>`).join('')}</div><div class="unit">${sp.unit || ''}</div></div>`;
  }

  function renderThumbs() {
    const P = manifest.products[state.product];
    const box = $('thumbs');
    box.innerHTML = '';
    for (const p of P.periods) {
      const f = currentField(p.id);
      const sp = spec(f, p);
      const c = renderer.render(sp.layers, sp.color, 150);
      renderer.outline(c);
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'thumb' + (p.id === state.period ? ' on' : '');
      card.appendChild(c);
      const cap = document.createElement('div');
      cap.innerHTML = `<b>${p.label}</b><small>${K.fmtDate(p.start)}–${K.fmtDate(p.end)}</small>`;
      card.appendChild(cap);
      card.onclick = () => { state.period = p.id; update(); };
      box.appendChild(card);
    }
  }

  // ---------------------------------------------------------------- 마우스 값 표시
  function onHover(e) {
    const box = $('hoverBox');
    const { lat, lng } = e.latlng;
    if (!renderer || !state.spec || !renderer.isLand(lat, lng)) { box.hidden = true; return; }
    const sp = state.spec;
    const vals = sp.layers.map((l) => renderer.sample(renderer.nodes(l), lat, lng));
    const V = manifest.variables[state.var];
    const P = K.POLES[state.var];
    let html;
    if (sp.legend === 'tercile') {
      html = `<div class="tri"><span>${P.lowName} <b>${K.fmt(vals[0], 0)}%</b></span><span>비슷 <b>${K.fmt(vals[1], 0)}%</b></span><span>${P.highName} <b>${K.fmt(vals[2], 0)}%</b></span></div>`;
    } else {
      html = `<b>${K.fmt(vals[0], sp.unit === '%' ? 0 : K.VAR_META[state.var].fmt)}</b> ${sp.unit || ''}`;
    }
    const city = K.nearestCity(lat, lng);
    box.innerHTML = `<div class="hl">${city ? city + ' 부근 · ' : ''}${lat.toFixed(2)}°N ${lng.toFixed(2)}°E</div>${html}<div class="hint">클릭: 지점 상세</div>`;
    const pt = e.containerPoint;
    const W = map.getSize().x;
    box.style.left = Math.min(pt.x + 14, W - 210) + 'px';
    box.style.top = pt.y + 14 + 'px';
    box.hidden = false;
  }

  // ---------------------------------------------------------------- 지점 창
  function openPoint(lat, lon) {
    const { index } = K.nearestPoint(grid, lat, lon);
    state.openIdx = index;
    const [la, lo] = grid.points[index];
    if (selMarker) selMarker.setLatLng([la, lo]);
    else selMarker = L.circleMarker([la, lo], { pane: 'labels', radius: 7, className: 'selpt', interactive: false }).addTo(map);
    const city = K.nearestCity(la, lo);
    $('pointWinTitle').textContent = `${city ? city + ' · ' : ''}격자 ${la.toFixed(1)}°N ${lo.toFixed(1)}°E` +
      (state.issue === 'latest' ? '' : ' (지점 상세는 최신 발표 기준)');
    setFrame(index);
    const w = $('pointWin');
    if (w.hidden) {
      w.hidden = false;
      if (!w.style.left && innerWidth > 900) {
        w.style.left = Math.max(innerWidth - w.offsetWidth - 24, 16) + 'px';
        w.style.top = '84px';
      }
    }
  }
  function setFrame(i) {
    const src = `point.html?i=${i}&p=${state.product}&v=${state.var}&period=${state.period}&embed=1`;
    const fr = $('pointFrame');
    if (fr.getAttribute('src') !== src) fr.setAttribute('src', src);
  }

  function makeDraggable(win, bar) {
    let sx, sy, ox, oy;
    bar.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button') || innerWidth <= 900) return;
      sx = e.clientX; sy = e.clientY;
      ox = win.offsetLeft; oy = win.offsetTop;
      bar.setPointerCapture(e.pointerId);
      win.classList.add('dragging');
    });
    bar.addEventListener('pointermove', (e) => {
      if (sx == null) return;
      win.style.left = Math.min(Math.max(ox + e.clientX - sx, 0), innerWidth - 120) + 'px';
      win.style.top = Math.min(Math.max(oy + e.clientY - sy, 0), innerHeight - 40) + 'px';
    });
    const end = () => { sx = null; win.classList.remove('dragging'); };
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
  }

  init();
})();
