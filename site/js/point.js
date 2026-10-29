/* 지점 상세: 기간별 3분위 확률, 일별 앙상블 시계열, 멤버 분포, 통계표 */
(function () {
  'use strict';
  const K = window.KCO;
  const $ = (id) => document.getElementById(id);
  const q = new URLSearchParams(location.search);
  const st = { i: +(q.get('i') || 0), p: q.get('p') || '1m', v: q.get('v') || 't2m', period: q.get('period'), ts: 'daily' };
  if (q.get('embed')) document.body.classList.add('embed');
  let manifest, grid, data;

  const EC_LABEL = {
    temperature_2m_anomaly_gt0: '기온 편차 > 0°C', temperature_2m_anomaly_gt1: '기온 편차 > +1°C', temperature_2m_anomaly_gt2: '기온 편차 > +2°C',
    temperature_2m_anomaly_ltm1: '기온 편차 < −1°C', temperature_2m_anomaly_ltm2: '기온 편차 < −2°C',
    precipitation_anomaly_gt0: '강수 편차 > 0 mm', precipitation_anomaly_gt10: '강수 편차 > 10 mm', precipitation_anomaly_gt20: '강수 편차 > 20 mm',
    temperature_2m_efi: '기온 EFI (−1~1)', precipitation_efi: '강수 EFI (−1~1)',
  };

  async function init() {
    try {
      [manifest, grid] = await Promise.all([K.getJSON(K.DATA + 'manifest.json'), K.getJSON('data/grid.json')]);
      data = await K.getJSON(K.DATA + `points/${st.i}.json`);
    } catch (e) {
      $('ptTitle').textContent = '자료를 불러올 수 없습니다';
      console.error(e);
      return;
    }
    if (!data[st.p]) st.p = Object.keys(manifest.products).find((k) => data[k]);
    if (!manifest.variables[st.v]) st.v = 't2m';
    try { const t = localStorage.getItem('kco-theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* 무시 */ }
    render();
    let rt;
    addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderCharts, 120); });
  }

  function seg(elm, items, cur, pick) {
    elm.innerHTML = '';
    for (const [val, label] of items) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = val === cur ? 'on' : '';
      b.setAttribute('aria-pressed', String(val === cur));
      b.innerHTML = label;
      b.onclick = () => pick(val);
      elm.appendChild(b);
    }
  }

  function render() {
    const P = manifest.products[st.p];
    const V = manifest.variables[st.v];
    const city = K.nearestCity(data.lat, data.lon);
    document.title = `${city || ''} ${data.lat}°N ${data.lon}°E · ${P.name}`;
    $('ptTitle').textContent = `${city ? city + ' 부근 · ' : ''}${data.lat.toFixed(1)}°N ${data.lon.toFixed(1)}°E`;
    $('ptSub').textContent = `${P.name} · ${P.model} · 발표 ${manifest.issued.slice(0, 10)}${manifest.demo ? ' · DEMO 합성자료' : ''} · 0.5° 격자값`;
    seg($('pProductSeg'), Object.entries(manifest.products).map(([k, p]) => [k, p.name]), st.p, (v) => { st.p = v; sync(); render(); });
    const tabs = $('varTabs');
    tabs.innerHTML = '';
    for (const [k, vv] of Object.entries(manifest.variables)) {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(k === st.v));
      b.innerHTML = `<span aria-hidden="true">${K.VAR_META[k].icon}</span> ${vv.name} <small>${vv.unit}</small>`;
      b.onclick = () => { st.v = k; sync(); render(); };
      tabs.appendChild(b);
    }
    $('tsTitle').textContent = `일별 앙상블 시계열 — ${V.name}`;
    if (V.agg !== 'sum') st.ts = 'daily';
    else if (st.tsVar !== st.v) st.ts = 'cum'; // 강수는 누적 그래프가 기본
    st.tsVar = st.v;
    const modes = V.agg === 'sum' ? [['daily', '일별'], ['cum', '누적']] : [['daily', '일별']];
    const pickTs = (v) => { st.ts = v; seg($('tsMode'), modes, st.ts, pickTs); renderCharts(); };
    seg($('tsMode'), modes, st.ts, pickTs);
    renderTercile();
    renderCharts();
    renderTable();
  }

  function sync() {
    const u = new URLSearchParams(location.search);
    u.set('p', st.p);
    u.set('v', st.v);
    history.replaceState(null, '', '?' + u.toString());
  }

  const periodsOf = () => manifest.products[st.p].periods;
  const rowOf = (pid) => data[st.p].periods[st.v][pid];

  // ---------------------------------------------------------------- 3분위 막대
  function renderTercile() {
    const P = K.POLES[st.v];
    const lowC = P.low[2], highC = P.high[2];
    const box = $('tercileBars');
    $('tercHint').textContent = `평년 확률은 각 33% · ${P.lowName}/비슷/${P.highName}`;
    box.innerHTML = periodsOf().map((p) => {
      const r = rowOf(p.id);
      if (!r) return '';
      const parts = [[r.below, lowC, P.lowName, '#fff'], [r.near, K.NEAR, '비슷', '#0b0b0b'], [r.above, highC, P.highName, '#fff']];
      const max = Math.max(r.below, r.near, r.above);
      const dom = max < 40 ? '뚜렷한 우세 범주 없음' : r.above === max ? `${P.highName} 우세` : r.below === max ? `${P.lowName} 우세` : '평년과 비슷 우세';
      return `<div class="tbar ${p.id === st.period ? 'cur' : ''}">
        <div class="tl"><b>${p.label}</b><small>${K.fmtDate(p.start)}–${K.fmtDate(p.end)}</small></div>
        <div class="tb" role="img" aria-label="${p.label}: ${P.lowName} ${r.below}%, 비슷 ${r.near}%, ${P.highName} ${r.above}%">
          ${parts.map(([v, c, n, ink]) => `<span style="flex:${Math.max(v, 0.5)};background:${c};color:${ink}" title="${n} ${v}%">${v >= 12 ? v + '%' : ''}</span>`).join('')}
          <i class="third" style="left:33.33%"></i><i class="third" style="left:66.67%"></i>
        </div>
        <div class="tr"><b>${dom}</b><small>중앙값 초과 ${r.gt_median}%</small></div>
      </div>`;
    }).join('');
  }

  // ---------------------------------------------------------------- 차트
  function renderCharts() {
    const V = manifest.variables[st.v];
    const D = data[st.p];
    const d = D.daily[st.v];
    const blue = '#2a78d6', blueD = '#1c5cab';
    const dg = K.VAR_META[st.v].fmt;
    const ink2 = getComputedStyle(document.documentElement).getPropertyValue('--ink-2').trim() || '#52514e';
    let bands, lines, rows, unit = V.unit;
    if (st.ts === 'cum' && d.cum) {
      let acc = 0;
      const normalCum = d.normal ? d.normal.map((v) => (v == null ? null : +(acc += v).toFixed(1))) : null;
      bands = [
        { lo: d.cum.p10, hi: d.cum.p90, color: blue, opacity: 0.18, label: '10–90%' },
        { lo: d.cum.p25, hi: d.cum.p75, color: blue, opacity: 0.32, label: '25–75%' },
      ];
      lines = [{ v: d.cum.p50, color: blueD, width: 2, label: '중앙값' }];
      if (normalCum) lines.push({ v: normalCum, color: ink2, width: 1.6, dash: '5 4', label: '평년 누적(ERA5)' });
      rows = (i) => [['90%', K.fmt(d.cum.p90[i], 0) + ' mm'], ['중앙값', K.fmt(d.cum.p50[i], 0) + ' mm', blueD], ['10%', K.fmt(d.cum.p10[i], 0) + ' mm'],
        ...(normalCum ? [['평년 누적', K.fmt(normalCum[i], 0) + ' mm', ink2]] : [])];
      unit = 'mm (누적)';
    } else {
      bands = [
        { lo: d.min, hi: d.max, color: blue, opacity: 0.08, label: '최소–최대' },
        { lo: d.p10, hi: d.p90, color: blue, opacity: 0.16, label: '10–90%' },
        { lo: d.p25, hi: d.p75, color: blue, opacity: 0.3, label: '25–75%' },
      ];
      lines = [{ v: d.p50, color: blueD, width: 2, label: '중앙값' }];
      if (d.normal) lines.push({ v: d.normal, color: ink2, width: 1.6, dash: '5 4', label: '일평년값(ERA5)' });
      const u = ' ' + V.unit;
      rows = (i) => [['최대', K.fmt(d.max[i], dg) + u], ['90%', K.fmt(d.p90[i], dg) + u], ['중앙값', K.fmt(d.p50[i], dg) + u, blueD],
        ['평균', K.fmt(d.mean[i], dg) + u], ['10%', K.fmt(d.p10[i], dg) + u], ['최소', K.fmt(d.min[i], dg) + u],
        ...(d.normal ? [['평년', K.fmt(d.normal[i], dg) + u, ink2]] : [])];
    }
    K.charts.plume($('tsChart'), {
      dates: D.dates, bands, lines, rows, unit, periods: periodsOf().filter((p) => p.kind !== 'season' && !(st.p === '1m' && p.id === 'm1')),
      zeroBase: V.agg === 'sum' || st.v !== 't2m', aria: `${V.name} 일별 앙상블 분포`,
    });
    $('tsLegend').innerHTML = [...bands.map((b) => `<span><i class="band" style="background:${b.color};opacity:${Math.min(1, b.opacity * 2.4)}"></i>${b.label}</span>`),
      ...lines.map((l) => `<span><i class="ln ${l.dash ? 'dash' : ''}" style="border-color:${l.color}"></i>${l.label}</span>`)].join('');

    const P = K.POLES[st.v];
    K.charts.distribution($('distChart'), periodsOf().map((p) => {
      const r = rowOf(p.id);
      return { label: p.label, sub: `${K.fmtDate(p.start)}–${K.fmtDate(p.end)}`, members: r.members, q: r.q, bounds: r.bounds, mean: r.mean, clim: r.clim, row: r };
    }), {
      low: P.low[2], high: P.high[2], near: '#a9a7a0', unit: `${V.unit}${V.agg === 'sum' ? ' (기간 누적)' : ' (기간 평균)'}`, zeroBase: V.agg === 'sum',
      tip: (r) => `<div class="th">${r.label} ${r.sub}</div>
        <div class="tr"><i></i><span>앙상블 평균</span><b>${K.fmt(r.mean, dg)}</b></div>
        <div class="tr"><i></i><span>평년값</span><b>${K.fmt(r.clim, dg)}</b></div>
        <div class="tr"><i style="background:${P.low[2]}"></i><span>평년 하위 1/3 경계</span><b>${K.fmt(r.bounds[1], dg)}</b></div>
        <div class="tr"><i style="background:${P.high[2]}"></i><span>평년 상위 1/3 경계</span><b>${K.fmt(r.bounds[3], dg)}</b></div>
        <div class="tr"><i></i><span>${P.lowName}/비슷/${P.highName}</span><b>${r.row.below}/${r.row.near}/${r.row.above}%</b></div>`,
    });
  }

  // ---------------------------------------------------------------- 표
  function tableRows() {
    const V = manifest.variables[st.v];
    const P = K.POLES[st.v];
    const dg = K.VAR_META[st.v].fmt;
    const per = periodsOf();
    const R = per.map((p) => rowOf(p.id));
    const f = (v, d = dg) => K.fmt(v, d);
    const rows = [
      ['group', '값'],
      ['앙상블 평균', R.map((r) => f(r.mean))],
      ['모델 평년값', R.map((r) => f(r.clim) + (r.clim_src === 'era5' ? '<sup title="ERA5 평년값 사용(모델 편차 미보정)">E</sup>' : ''))],
      [V.mode === 'add' ? '평년편차' : '평년편차 (평년비)', R.map((r) => (r.anom > 0 ? '+' : '') + f(r.anom) + (V.mode === 'mul' ? ` (${f(r.anom_pct, 0)}%)` : ''))],
      ['앙상블 스프레드(σ)', R.map((r) => f(r.spread))],
      ['멤버 10%', R.map((r) => f(r.q[0]))],
      ['멤버 25%', R.map((r) => f(r.q[1]))],
      ['멤버 중앙값', R.map((r) => f(r.q[2]))],
      ['멤버 75%', R.map((r) => f(r.q[3]))],
      ['멤버 90%', R.map((r) => f(r.q[4]))],
      ['ECMWF 직접 편차', R.map((r) => (r.api_anom == null ? '–' : (r.api_anom > 0 ? '+' : '') + f(r.api_anom, 2)))],
      ['group', '평년 분포 경계'],
      ['하위 10% 경계', R.map((r) => f(r.bounds[0]))],
      ['하위 1/3 경계', R.map((r) => f(r.bounds[1]))],
      ['평년 중앙값', R.map((r) => f(r.bounds[2]))],
      ['상위 1/3 경계', R.map((r) => f(r.bounds[3]))],
      ['상위 10% 경계', R.map((r) => f(r.bounds[4]))],
      ['group', '확률 (%)'],
      [`${P.lowName} (하위 1/3)`, R.map((r) => r.below), 'low'],
      ['평년과 비슷', R.map((r) => r.near), 'near'],
      [`${P.highName} (상위 1/3)`, R.map((r) => r.above), 'high'],
      ['평년 중앙값 초과', R.map((r) => r.gt_median), 'p'],
      [`매우 ${P.lowName} (하위 10%)`, R.map((r) => r.lt_p10), 'p'],
      [`매우 ${P.highName} (상위 10%)`, R.map((r) => r.gt_p90), 'p'],
      ['group', '임계값별 발생확률 (%)'],
    ];
    const keys = [...new Set(R.flatMap((r) => Object.keys(r.thr)))];
    for (const k of keys) rows.push([K.thresholdLabel(k, V), R.map((r) => (r.thr[k] == null ? '–' : r.thr[k])), 'p']);
    return { per, rows };
  }

  function probCell(v, kind) {
    if (v === '–' || v == null) return '<td>–</td>';
    const P = K.POLES[st.v];
    const c = kind === 'low' ? P.low[2] : kind === 'high' ? P.high[2] : kind === 'near' ? '#898781' : 'var(--accent)';
    return `<td class="pc"><span class="pbar" style="width:${Math.min(v, 100)}%;background:${c}"></span><b>${v}</b></td>`;
  }

  function renderTable() {
    const { per, rows } = tableRows();
    const V = manifest.variables[st.v];
    const head = `<thead><tr><th>${V.name} (${V.unit})</th>${per.map((p) => `<th class="${p.id === st.period ? 'cur' : ''}">${p.label}<small>${K.fmtDate(p.start)}–${K.fmtDate(p.end)}</small></th>`).join('')}</tr></thead>`;
    const body = rows.map(([lab, vals, kind]) => {
      if (lab === 'group') return `<tr class="grp"><th colspan="${per.length + 1}">${vals}</th></tr>`;
      return `<tr><th>${lab}</th>${vals.map((v) => (kind ? probCell(v, kind) : `<td>${v}</td>`)).join('')}</tr>`;
    }).join('');
    $('statTable').innerHTML = head + '<tbody>' + body + '</tbody>';
    $('tableNote').innerHTML = `${V.agg === 'sum' ? '기간 누적' : '기간 평균'} 기준. 확률은 ${manifest.products[st.p].members[st.v] || 51}개 멤버 중 해당 조건을 만족하는 멤버의 비율. ` +
      '평년값은 ECMWF 모델 기후값(= 예측 − ECMWF 편차)으로 모델의 계통오차를 제거했으며, ' +
      '<sup>E</sup> 표시는 ECMWF 편차를 쓸 수 없어 ERA5 평년값을 사용한 경우. 평년 분포 경계는 ERA5 1991–2020 동일 기간 30년 분포의 형태를 모델 평년값에 적용.';

    const ec = data[st.p].ec46_probs;
    const weeks = per.filter((p) => p.kind === 'week');
    const keys = ec ? [...new Set(weeks.flatMap((p) => Object.keys(ec[p.id] || {})))] : [];
    $('ecTableBox').hidden = !keys.length;
    if (keys.length) {
      $('ecTable').innerHTML = `<thead><tr><th>항목</th>${weeks.map((p) => `<th>${p.label}<small>${K.fmtDate(p.start)}–${K.fmtDate(p.end)}</small></th>`).join('')}</tr></thead><tbody>` +
        keys.map((k) => `<tr><th>${EC_LABEL[k] || k}</th>${weeks.map((p) => {
          const v = (ec[p.id] || {})[k];
          return /efi/.test(k) ? `<td>${v == null ? '–' : (+v).toFixed(2)}</td>` : probCell(v == null ? '–' : Math.round(v), 'p');
        }).join('')}</tr>`).join('') + '</tbody>';
    }
    $('csvBtn').onclick = downloadCSV;
  }

  function downloadCSV() {
    const { per, rows } = tableRows();
    const V = manifest.variables[st.v];
    const strip = (s) => String(s).replace(/<[^>]+>/g, '');
    const lines = [[`${V.name}(${V.unit})`, ...per.map((p) => `${p.label} ${p.start}~${p.end}`)].join(',')];
    for (const [lab, vals] of rows) if (lab !== 'group') lines.push([lab, ...vals.map(strip)].map((x) => `"${x}"`).join(','));
    const d = data[st.p].daily[st.v];
    lines.push('', ['date', 'min', 'p10', 'p25', 'p50', 'p75', 'p90', 'max', 'mean', 'normal_ERA5'].join(','));
    data[st.p].dates.forEach((dt, i) => lines.push([dt, d.min[i], d.p10[i], d.p25[i], d.p50[i], d.p75[i], d.p90[i], d.max[i], d.mean[i], d.normal ? d.normal[i] : ''].join(',')));
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `outlook_${st.p}_${st.v}_${data.lat}N_${data.lon}E.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  init();
})();
