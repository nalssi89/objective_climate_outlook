/* 격자값 → 한반도 육상만 칠한 메르카토르 이미지 (Leaflet imageOverlay 와 정확히 겹침) */
(function (global) {
  'use strict';
  const R = Math.PI / 180;
  const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * R) / 2));
  const imerc = (y) => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / R;

  const rgbCache = {};
  function rgb(hex) {
    if (!rgbCache[hex]) {
      const n = parseInt(hex.slice(1), 16);
      rgbCache[hex] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    return rgbCache[hex];
  }

  class FieldRenderer {
    constructor(grid, koreaGeo) {
      this.grid = grid;
      this.geo = koreaGeo;
      const h = grid.step / 2;
      this.south = grid.lats[0] - h;
      this.north = grid.lats[grid.lats.length - 1] + h;
      this.west = grid.lons[0] - h;
      this.east = grid.lons[grid.lons.length - 1] + h;
      this.masks = {};
    }
    get bounds() {
      return [[this.south, this.west], [this.north, this.east]];
    }
    size(width) {
      const span = (this.east - this.west) * R;
      const height = Math.round((width * (merc(this.north) - merc(this.south))) / span);
      return [width, height];
    }
    toPixel(lat, lon, W, H) {
      const x = ((lon - this.west) / (this.east - this.west)) * W;
      const y = ((merc(this.north) - merc(lat)) / (merc(this.north) - merc(this.south))) * H;
      return [x, y];
    }
    mask(W, H) {
      const key = W + 'x' + H;
      if (this.masks[key]) return this.masks[key];
      const c = document.createElement('canvas');
      c.width = W;
      c.height = H;
      const ctx = c.getContext('2d');
      ctx.fillStyle = '#000';
      ctx.beginPath();
      for (const f of this.geo.features) {
        const g = f.geometry;
        const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
        for (const poly of polys) {
          for (const ring of poly) {
            ring.forEach(([lo, la], i) => {
              const [x, y] = this.toPixel(la, lo, W, H);
              i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
            });
            ctx.closePath();
          }
        }
      }
      ctx.fill('evenodd');
      const alpha = ctx.getImageData(0, 0, W, H).data;
      return (this.masks[key] = { canvas: c, alpha });
    }
    // 육상 격자값(points 순서)을 사각 격자 노드로 확장
    nodes(vals) {
      const g = this.grid;
      return g.fill_index.map((k) => (vals[k] == null ? NaN : vals[k]));
    }
    // 위경도 지점의 쌍선형 보간값
    sample(nodeVals, lat, lon) {
      const g = this.grid;
      const ny = g.lats.length, nx = g.lons.length;
      let fi = (lat - g.lats[0]) / g.step, fj = (lon - g.lons[0]) / g.step;
      fi = Math.min(Math.max(fi, 0), ny - 1.0001);
      fj = Math.min(Math.max(fj, 0), nx - 1.0001);
      const i = Math.floor(fi), j = Math.floor(fj), di = fi - i, dj = fj - j;
      const v00 = nodeVals[i * nx + j], v01 = nodeVals[i * nx + j + 1], v10 = nodeVals[(i + 1) * nx + j], v11 = nodeVals[(i + 1) * nx + j + 1];
      return v00 * (1 - di) * (1 - dj) + v01 * (1 - di) * dj + v10 * di * (1 - dj) + v11 * di * dj;
    }
    /**
     * layers: 육상 격자값 배열들 (1개=스칼라, 3개=3분위 확률)
     * color: (...보간값) => '#rrggbb' | null
     */
    render(layers, color, width = 560) {
      const [W, H] = this.size(width);
      const nodes = layers.map((v) => this.nodes(v));
      const c = document.createElement('canvas');
      c.width = W;
      c.height = H;
      const ctx = c.getContext('2d');
      const img = ctx.createImageData(W, H);
      const m = this.mask(W, H).alpha;
      const yN = merc(this.north), yS = merc(this.south);
      const vals = new Array(layers.length);
      for (let py = 0; py < H; py++) {
        const lat = imerc(yN - ((py + 0.5) / H) * (yN - yS));
        for (let px = 0; px < W; px++) {
          const o = (py * W + px) * 4;
          if (m[o + 3] < 8) continue;
          const lon = this.west + ((px + 0.5) / W) * (this.east - this.west);
          for (let k = 0; k < nodes.length; k++) vals[k] = this.sample(nodes[k], lat, lon);
          const col = color(...vals);
          if (!col) continue;
          const [r, g, b] = rgb(col);
          img.data[o] = r;
          img.data[o + 1] = g;
          img.data[o + 2] = b;
          img.data[o + 3] = m[o + 3];
        }
      }
      ctx.putImageData(img, 0, 0);
      return c;
    }
    isLand(lat, lon, width = 560) {
      const [W, H] = this.size(width);
      const [x, y] = this.toPixel(lat, lon, W, H);
      if (x < 0 || y < 0 || x >= W || y >= H) return false;
      return this.mask(W, H).alpha[(Math.floor(y) * W + Math.floor(x)) * 4 + 3] > 64;
    }
    // 작은 그림(기간 비교)용: 경계선까지 그린 캔버스
    outline(canvas, stroke = 'rgba(60,60,60,.55)') {
      const ctx = canvas.getContext('2d');
      const W = canvas.width, H = canvas.height;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = Math.max(0.6, W / 400);
      for (const f of this.geo.features) {
        const g = f.geometry;
        const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
        for (const poly of polys) {
          for (const ring of poly) {
            ctx.beginPath();
            ring.forEach(([lo, la], i) => {
              const [x, y] = this.toPixel(la, lo, W, H);
              i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
            });
            ctx.closePath();
            ctx.stroke();
          }
        }
      }
    }
  }
  global.KCO.FieldRenderer = FieldRenderer;
})(window);
