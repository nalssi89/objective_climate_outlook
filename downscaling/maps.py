"""상세예측 지도 PNG (matplotlib). 경계는 site/data/geo 의 GeoJSON을 쓴다."""
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "site" / "data" / "geo"
INK = "#1f1f1c"
DIV_T = mcolors.LinearSegmentedColormap.from_list("t", ["#104281", "#3987e5", "#b7d3f6", "#f0efec", "#f7c4b8", "#e34948", "#8f1d1d"])
DIV_P = mcolors.LinearSegmentedColormap.from_list("p", ["#7a4a12", "#c98500", "#f3dca3", "#f0efec", "#a8dcc6", "#1baf7a", "#0b5e40"])
BOX = (123.6, 33.0, 131.2, 43.1)
try:
    import koreanize_matplotlib  # noqa: F401
except ImportError:
    pass
plt.rcParams.update({"axes.unicode_minus": False, "font.size": 8, "figure.dpi": 140})


def _lines():
    segs = []
    for f in ("korea.geojson", "neighbors.geojson"):
        p = GEO / f
        if not p.exists():
            continue
        for ft in json.load(open(p))["features"]:
            g = ft["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            for poly in polys:
                for ring in poly:
                    segs.append(np.asarray(ring))
    return segs


SEGS = None


def base(ax, title=None):
    global SEGS
    SEGS = SEGS if SEGS is not None else _lines()
    for s in SEGS:
        ax.plot(s[:, 0], s[:, 1], color="#55554f", lw=0.45)
    ax.set_xlim(BOX[0], BOX[2]); ax.set_ylim(BOX[1], BOX[3])
    ax.set_aspect(1 / np.cos(np.deg2rad(38))); ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color("#c3c2b7")
    if title:
        ax.set_title(title, loc="left", fontsize=8, color=INK)


def field(ax, vals, lat, lon, cmap, levels):
    la = np.round(np.arange(lat.min(), lat.max() + 0.01, 0.25), 2)
    lo = np.round(np.arange(lon.min(), lon.max() + 0.01, 0.25), 2)
    G = np.full((len(la), len(lo)), np.nan)
    G[np.searchsorted(la, np.round(lat, 2)), np.searchsorted(lo, np.round(lon, 2))] = vals
    d = 0.125
    return ax.pcolormesh(np.r_[lo - d, lo[-1] + d], np.r_[la - d, la[-1] + d], G, cmap=cmap,
                         norm=mcolors.BoundaryNorm(levels, cmap.N), shading="flat")


def draw_all(out, products):
    from forecast import load_model
    g = load_model("grid", "T", "week")
    lat, lon = g["lat"], g["lon"]
    for scale, P in products.items():
        per = P["periods"]; nb = len(per)
        if nb == 0:
            continue
        fig, axs = plt.subplots(4, nb, figsize=(1.9 * nb + 1.3, 9.6), squeeze=False)
        for b, it in enumerate(per):
            T, Pp = it["grid_T"], it["grid_P"]
            i1 = field(axs[0, b], T["anom"], lat, lon, DIV_T, np.arange(-3, 3.01, 0.5)); base(axs[0, b], it["label"])
            dom = np.where(T["above"] >= T["below"], T["above"], -T["below"]) * 100
            i2 = field(axs[1, b], dom, lat, lon, DIV_T, [-100, -70, -60, -50, -40, 40, 50, 60, 70, 100]); base(axs[1, b])
            i3 = field(axs[2, b], Pp["pct"], lat, lon, DIV_P, [0, 40, 60, 80, 90, 110, 120, 150, 200, 300]); base(axs[2, b])
            domp = np.where(Pp["above"] >= Pp["below"], Pp["above"], -Pp["below"]) * 100
            i4 = field(axs[3, b], domp, lat, lon, DIV_P, [-100, -70, -60, -50, -40, 40, 50, 60, 70, 100]); base(axs[3, b])
        for ax, im, lab in ((axs[0], i1, "기온 편차 (°C)"), (axs[1], i2, "기온 우세범주 확률 (%)\n-낮음 / +높음"),
                            (axs[2], i3, "강수 평년비 (%)"), (axs[3], i4, "강수 우세범주 확률 (%)\n-적음 / +많음")):
            fig.colorbar(im, ax=ax, shrink=0.85, label=lab)
        nm = "주별(EC46)" if scale == "week" else "월별(SEAS5)"
        fig.suptitle(f"한반도 0.25° 상세예측 — {nm}, 발표 {P['issued']}", x=0.01, ha="left", fontsize=11, color=INK)
        fig.savefig(Path(out) / f"map_{scale}.png", bbox_inches="tight"); plt.close(fig)
