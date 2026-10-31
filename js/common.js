/* 공통: 자료 적재, 요소·표출항목 정의, 색 척도 */
(function (global) {
  'use strict';

  const DATA = 'data/latest/';
  const cache = {};
  async function getJSON(path) {
    if (!cache[path]) {
      cache[path] = fetch(path, { cache: 'no-cache' }).then((r) => {
        if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
        return r.json();
      });
    }
    return cache[path];
  }

  // 요소별 색 (낮음/높음 쪽 극) — 3분위 범주색과 편차 척도 공통
  const POLES = {
    t2m: { low: ['#0d366b', '#1c5cab', '#3987e5', '#86b6ef', '#cde2fb'], high: ['#fbd5cf', '#f39b8f', '#e34948', '#b52a2a', '#7a1414'],
      lowName: '낮음', highName: '높음' },
    precip: { low: ['#5c3208', '#8a4d12', '#b8742a', '#dcae6e', '#f2dfc0'], high: ['#c7ecd9', '#7fcfa8', '#1baf7a', '#0b7a52', '#044a31'],
      lowName: '적음', highName: '많음' },
    rad: { low: ['#2e2470', '#4a3aa7', '#6250d6', '#a59cec', '#dcd8f8'], high: ['#fde9b8', '#f8cd5c', '#eda100', '#b87a00', '#7a5000'],
      lowName: '적음', highName: '많음' },
    wind: { low: ['#0b5b40', '#138a62', '#1baf7a', '#7fd3b2', '#cdeee0'], high: ['#e1dcf8', '#b3a8ef', '#7f6fe0', '#5341b8', '#33267f'],
      lowName: '약함', highName: '강함' },
  };
  const NEUTRAL = '#e9e8e4';
  const NEAR = '#a9a7a0';

  const VAR_META = {
    t2m: { short: '기온', icon: '🌡', meanBreaks: [-15, -10, -6, -3, 0, 3, 6, 10, 15, 20, 25], fmt: 1 },
    precip: { short: '강수', icon: '☔', fmt: 0 },
    rad: { short: '일사', icon: '☀', fmt: 1 },
    wind: { short: '풍속', icon: '🌬', fmt: 1 },
  };

  // 표출 항목
  const PRODUCTS = {
    tercile: { name: '3분위 확률 (우세 범주)', desc: '평년(1991–2020) 분포를 셋으로 나눈 낮음·비슷·높음 범주 가운데 확률이 가장 큰 범주와 그 확률. WMO 장기예보 표준 형식.' },
    median: { name: '평년(중앙값)보다 높을 확률', desc: '호주기상청(BoM) 방식. 50%보다 크면 평년보다 높을 가능성이 더 큼.' },
    mean: { name: '앙상블 평균', desc: '51개 앙상블 멤버의 평균값(기간 평균 또는 누적).' },
    anom: { name: '평년편차', desc: '앙상블 평균 − 모델 평년값. 강수·일사·풍속은 평년비(%)로 표시. 독일기상청(DWD) 편차도 형식.' },
    threshold: { name: '임계값 초과(미만) 확률', desc: '앙상블 멤버 중 선택한 임계값을 넘는(밑도는) 멤버의 비율.' },
    extreme: { name: '극한 확률 (상·하위 10%)', desc: '평년 분포의 상위 10% 이상 또는 하위 10% 이하가 될 확률. 평년 확률은 각 10%.' },
    spread: { name: '앙상블 스프레드', desc: '멤버 간 표준편차. 클수록 예측 불확실성이 큼.' },
  };

  function steps(breaks, colors, opts = {}) {
    return { type: 'steps', breaks, colors, ...opts };
  }
  function colorOf(scale, v) {
    if (v == null || !isFinite(v)) return null;
    let i = 0;
    while (i < scale.breaks.length && v >= scale.breaks[i]) i++;
    return scale.colors[i];
  }

  function scaleFor(product, vk, opts = {}) {
    const P = POLES[vk];
    const lowRev = P.low; // 진한→연한
    const high = P.high; // 연한→진한
    switch (product) {
      case 'median':
        return steps([20, 30, 40, 45, 55, 60, 70, 80], [lowRev[0], lowRev[1], lowRev[2], lowRev[3], NEUTRAL, high[1], high[2], high[3], high[4]],
          { unit: '%', labels: ['', '20', '30', '40', '45', '55', '60', '70', '80'] });
      case 'threshold':
      case 'extreme': {
        const c = opts.side === 'low' ? lowRev.slice().reverse() : high;
        return steps([10, 20, 35, 50, 65, 80], ['#f4f3f0', c[0], c[1], c[2], c[3], c[4], darken(c[4])], { unit: '%' });
      }
      case 'spread':
        return steps(spreadBreaks(vk, opts.kind), ['#f2f1ee', '#dcd8f8', '#b3a8ef', '#7f6fe0', '#5341b8', '#33267f'], { unit: opts.unit });
      case 'anom':
        if (vk === 't2m') {
          return steps([-3, -2, -1, -0.5, -0.25, 0.25, 0.5, 1, 2, 3],
            [lowRev[0], lowRev[1], lowRev[2], lowRev[3], lowRev[4], NEUTRAL, high[0], high[1], high[2], high[3], high[4]], { unit: '°C' });
        }
        if (vk === 'precip') {
          return steps([25, 50, 70, 90, 110, 130, 150, 200, 300],
            [lowRev[0], lowRev[1], lowRev[2], lowRev[3], NEUTRAL, high[0], high[1], high[2], high[3], high[4]], { unit: '%' });
        }
        return steps([70, 80, 90, 95, 105, 110, 120, 130],
          [lowRev[0], lowRev[1], lowRev[2], lowRev[3], NEUTRAL, high[1], high[2], high[3], high[4]], { unit: '%' });
      case 'mean':
      default:
        return meanScale(vk, opts);
    }
  }

  function spreadBreaks(vk, kind) {
    const k = kind === 'week' ? 1 : kind === 'month' ? 0.7 : 0.5;
    if (vk === 't2m') return [0.5, 1, 1.5, 2, 3].map((x) => +(x * k).toFixed(2));
    if (vk === 'precip') return kind === 'week' ? [5, 10, 20, 30, 50] : kind === 'month' ? [10, 20, 40, 60, 100] : [20, 40, 70, 100, 150];
    if (vk === 'rad') return [0.5, 1, 1.5, 2, 3];
    return [0.2, 0.4, 0.6, 0.8, 1.2];
  }

  function meanScale(vk, opts) {
    if (vk === 't2m') {
      const P = POLES.t2m;
      return steps([-15, -10, -5, -2, 0, 2, 5, 10, 15, 20, 25],
        [P.low[0], P.low[1], P.low[2], P.low[3], P.low[4], '#f3f2ee', P.high[0], P.high[1], P.high[2], P.high[3], P.high[4], darken(P.high[4])], { unit: '°C' });
    }
    if (vk === 'precip') {
      const k = opts.kind === 'week' ? 1 : opts.kind === 'month' ? 4 : 12;
      const b = [2, 5, 10, 20, 35, 50, 75, 100].map((x) => Math.round(x * k));
      return steps(b, ['#f7f5ef', '#dff3e9', '#c7ecd9', '#a3dec0', '#7fcfa8', '#3dbb8c', '#1baf7a', '#0b7a52', '#044a31'], { unit: 'mm' });
    }
    if (vk === 'rad') {
      return steps([4, 6, 8, 10, 12, 15, 18, 21, 24], ['#f6f1e4', '#fdf2d3', '#fde9b8', '#fbdb87', '#f8cd5c', '#f3b72e', '#eda100', '#c98500', '#9a6600', '#6e4800'], { unit: 'MJ/m²' });
    }
    return steps([1.5, 2, 2.5, 3, 3.5, 4, 5, 6], ['#f2f1ee', '#e1dcf8', '#cbc3f3', '#b3a8ef', '#998be7', '#7f6fe0', '#5341b8', '#33267f', '#1f1757'], { unit: 'm/s' });
  }

  function darken(hex) {
    const n = parseInt(hex.slice(1), 16);
    const f = (x) => Math.max(0, Math.round(x * 0.7));
    return '#' + [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(f).map((x) => x.toString(16).padStart(2, '0')).join('');
  }

  // 3분위 우세 범주 색: 확률 구간 40/50/60/70
  function tercileColor(vk, b, n, a) {
    if (b == null || a == null) return null;
    const P = POLES[vk];
    const max = Math.max(b, n, a);
    const lvl = max >= 70 ? 3 : max >= 60 ? 2 : max >= 50 ? 1 : max >= 40 ? 0 : -1;
    if (lvl < 0) return '#f4f3f0'; // 불확실(어느 범주도 40% 미만)
    if (a === max) return P.high[lvl + 1];
    if (b === max) return P.low[3 - lvl];
    return ['#d9d8d3', '#c3c2b7', '#a9a7a0', '#898781'][lvl];
  }

  function fmt(v, d = 1) {
    if (v == null || !isFinite(v)) return '–';
    return Number(v).toFixed(d);
  }
  function fmtDate(s) {
    const [y, m, d] = s.split('-').map(Number);
    return `${m}/${d}`;
  }
  function dayName(s) {
    return '일월화수목금토'[new Date(s + 'T00:00:00').getDay()];
  }

  const CITIES = [
    ['서울', 37.57, 126.98], ['인천', 37.46, 126.71], ['수원', 37.26, 127.03], ['춘천', 37.88, 127.73], ['강릉', 37.75, 128.89],
    ['청주', 36.64, 127.49], ['대전', 36.35, 127.38], ['전주', 35.82, 127.15], ['광주', 35.16, 126.85], ['목포', 34.81, 126.39],
    ['대구', 35.87, 128.6], ['안동', 36.57, 128.73], ['울산', 35.54, 129.31], ['부산', 35.18, 129.08], ['여수', 34.76, 127.66],
    ['제주', 33.5, 126.53], ['울릉도', 37.48, 130.9], ['평양', 39.03, 125.75], ['개성', 37.97, 126.55], ['원산', 39.15, 127.44],
    ['함흥', 39.92, 127.54], ['신의주', 40.1, 124.4], ['강계', 40.97, 126.6], ['혜산', 41.4, 128.18], ['청진', 41.8, 129.78], ['삼지연', 41.82, 128.3],
  ];

  function nearestPoint(grid, lat, lon) {
    let best = 0, bd = Infinity;
    const c = Math.cos((lat * Math.PI) / 180);
    grid.points.forEach((p, i) => {
      const d = (p[0] - lat) ** 2 + ((p[1] - lon) * c) ** 2;
      if (d < bd) { bd = d; best = i; }
    });
    return { index: best, dist: Math.sqrt(bd) };
  }
  function nearestCity(lat, lon) {
    let best = null, bd = Infinity;
    const c = Math.cos((lat * Math.PI) / 180);
    for (const [n, la, lo] of CITIES) {
      const d = (la - lat) ** 2 + ((lo - lon) * c) ** 2;
      if (d < bd) { bd = d; best = n; }
    }
    return bd < 0.45 ** 2 ? best : null;
  }

  function thresholdLabel(key, V) {
    const unit = V.unit;
    let m;
    if ((m = key.match(/^anom_(gt|lt)([+-]?[\d.]+)$/))) return `평년편차 ${m[1] === 'gt' ? '>' : '<'} ${(+m[2] > 0 ? '+' : '') + +m[2]}${unit}`;
    if ((m = key.match(/^ratio_(gt|lt)(\d+)$/))) return `평년비 ${m[1] === 'gt' ? '>' : '<'} ${m[2]}%`;
    if ((m = key.match(/^abs_gt(\d+)$/))) return `기간 누적 > ${m[1]}${unit}`;
    return key;
  }
  const thresholdSide = (key) => (/_lt/.test(key) ? 'low' : 'high');

  global.KCO = {
    DATA, getJSON, POLES, NEAR, NEUTRAL, VAR_META, PRODUCTS, scaleFor, colorOf, tercileColor, fmt, fmtDate, dayName,
    CITIES, nearestPoint, nearestCity, thresholdLabel, thresholdSide,
  };
})(window);
