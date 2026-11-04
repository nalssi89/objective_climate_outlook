"""그림: 영역, 교차검증 기술, 모형 비교, 예보 지도."""
import os, sys
from pathlib import Path
import numpy as np, pandas as pd, xarray as xr
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import koreanize_matplotlib  # noqa: F401
sys.path.insert(0, str(Path(__file__).parent))
import mapbase

WORK = Path(os.environ.get("KDS_WORK", "work"))
FIG = Path(os.environ.get("KDS_FIG", "../docs")); FIG.mkdir(exist_ok=True, parents=True)
INK, INK2, GRID = "#1f1f1c", "#6b6a63", "#e1e0d9"
C_ESD, C_RAW = "#2a78d6", "#eb6834"
plt.rcParams.update({"axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.titlesize": 10, "font.size": 9, "axes.grid": False,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150, "axes.unicode_minus": False})
BOX = (123.5, 33.0, 131.5, 43.2)
DIV_T = mcolors.LinearSegmentedColormap.from_list("t", ["#104281", "#3987e5", "#b7d3f6", "#f0efec", "#f7c4b8", "#e34948", "#8f1d1d"])
DIV_P = mcolors.LinearSegmentedColormap.from_list("p", ["#7a4a12", "#c98500", "#f3dca3", "#f0efec", "#a8dcc6", "#1baf7a", "#0b5e40"])
SEQ = mcolors.LinearSegmentedColormap.from_list("s", ["#f0efec", "#b7d3f6", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"])


def to_grid(vals, lat, lon):
    la = np.round(np.arange(lat.min(), lat.max() + 0.01, 0.25), 2)
    lo = np.round(np.arange(lon.min(), lon.max() + 0.01, 0.25), 2)
    G = np.full((len(la), len(lo)), np.nan)
    G[np.searchsorted(la, np.round(lat, 2)), np.searchsorted(lo, np.round(lon, 2))] = vals
    return la, lo, G


def mapax(ax, title=None):
    mapbase.draw(ax, box=(BOX[0] - .5, BOX[1] - .5, BOX[2] + .5, BOX[3] + .5), color="#55554f", lw=0.5)
    ax.set_xlim(BOX[0], BOX[2]); ax.set_ylim(BOX[1], BOX[3])
    ax.set_xticks([124, 126, 128, 130]); ax.set_yticks([34, 36, 38, 40, 42])
    ax.set_xticklabels([f"{x}°E" for x in [124, 126, 128, 130]], fontsize=7)
    ax.set_yticklabels([f"{y}°N" for y in [34, 36, 38, 40, 42]], fontsize=7)
    if title:
        ax.set_title(title, loc="left", color=INK)


def field(ax, vals, lat, lon, cmap, vmin, vmax, levels=None):
    la, lo, G = to_grid(vals, lat, lon)
    d = 0.125
    norm = mcolors.BoundaryNorm(levels, cmap.N) if levels is not None else mcolors.Normalize(vmin, vmax)
    return ax.pcolormesh(np.r_[lo - d, lo[-1] + d], np.r_[la - d, la[-1] + d], G, cmap=cmap, norm=norm, shading="flat")


def skill(o, p):
    ok = np.isfinite(o) & np.isfinite(p)
    if ok.sum() < 10:
        return np.nan, np.nan
    return np.corrcoef(o[ok], p[ok])[0, 1], 1 - np.mean((o[ok] - p[ok]) ** 2) / np.mean(o[ok] ** 2)


def skill_table(kind, var, scale, period=(1991, 2022), src="cv", pooled=False):
    """점별 기술. pooled=False: 달별, True: 기간 전체(독립검증처럼 표본이 적을 때)"""
    ds = xr.open_dataset(WORK / f"cv_{kind}_{var}_{scale}.nc")
    t = ds.time.to_index(); rows = []
    for m in ([0] if pooled else range(1, 13)):
        c = ((t.month == m) | pooled) & (t.year >= period[0]) & (t.year <= period[1])
        for j in range(ds.sizes["pt"]):
            r, s = skill(ds.obs.values[c, j], ds[src].values[c, j])
            rb, sb = skill(ds.obs.values[c, j], ds.base.values[c, j])
            rows.append(dict(kind=kind, var=var, scale=scale, month=m, pt=j, lat=float(ds.lat[j]), lon=float(ds.lon[j]),
                             r=r, msess=s, r_raw=rb, msess_raw=sb))
    return pd.DataFrame(rows)


def fig_domain():
    pred = xr.open_dataset(WORK / "pred.nc"); g = xr.open_dataset(WORK / "target_grid.nc"); a = xr.open_dataset(WORK / "target_asos.nc")
    fig, ax = plt.subplots(1, 2, figsize=(10, 5.2), gridspec_kw=dict(width_ratios=[1.35, 1]))
    LO, LA = np.meshgrid(pred.lon, pred.lat)
    mapbase.draw(ax[0], box=(112, 26, 143, 48), color="#55554f", lw=0.4)
    ax[0].scatter(LO, LA, s=10, color=C_RAW, label="예측인자 1.5° 격자점 (247점)")
    ax[0].add_patch(plt.Rectangle((124, 33), 8, 10.5, fill=False, ec=C_ESD, lw=1.2, label="다운스케일 영역"))
    ax[0].legend(loc="lower right", fontsize=8, frameon=False); ax[0].set_title("예측인자 영역 (Open-Meteo 요청 좌표)", loc="left")
    m = g.mask.values
    field(ax[1], np.where(m, 1, np.nan)[m], *[np.meshgrid(g.lat, g.lon, indexing="ij")[i][m] for i in (0, 1)],
          mcolors.ListedColormap(["#cde2fb"]), 0, 2)
    ax[1].scatter(a.lon, a.lat, s=9, color=INK, label="ASOS 62지점")
    mapax(ax[1], f"타깃: ERA5 0.25° 육지 {int(m.sum())}격자 + ASOS")
    ax[1].legend(loc="upper left", fontsize=8, frameon=False)
    fig.tight_layout(); fig.savefig(FIG / "fig01_domain.png"); plt.close(fig)


def fig_skill_maps(tabs):
    fig, axs = plt.subplots(2, 4, figsize=(12, 7.6))
    combos = [("T", "week"), ("T", "month"), ("P", "week"), ("P", "month")]
    nm = {"T": "기온", "P": "강수", "week": "주평균", "month": "월평균"}
    for i, (v, s) in enumerate(combos):
        d = tabs[(v, s)].groupby("pt")[["lat", "lon", "r", "r_raw"]].mean()
        im = field(axs[0, i], d.r.values, d.lat.values, d.lon.values, SEQ, 0, 1, levels=np.arange(0.3, 1.01, 0.05))
        mapax(axs[0, i], f"{nm[v]} {nm[s]}  r={d.r.mean():.2f}")
        im2 = field(axs[1, i], (d.r - d.r_raw).values, d.lat.values, d.lon.values, DIV_T, -.3, .3,
                    levels=np.arange(-0.3, 0.31, 0.05))
        mapax(axs[1, i], f"원시 대비 Δr {(d.r - d.r_raw).mean():+.2f}")
    fig.colorbar(im, ax=axs[0], shrink=0.8, label="상관계수 (1991~2022, 연도별 교차검증)")
    fig.colorbar(im2, ax=axs[1], shrink=0.8, label="Δ상관 (다운스케일 - 원시 1.5°)")
    fig.savefig(FIG / "fig02_skill_maps.png", bbox_inches="tight"); plt.close(fig)


def fig_skill_month(tabs, tabs_asos):
    fig, axs = plt.subplots(1, 4, figsize=(13, 3.4), sharey=True)
    nm = {"T": "기온", "P": "강수", "week": "주평균", "month": "월평균"}
    for i, (v, s) in enumerate([("T", "week"), ("T", "month"), ("P", "week"), ("P", "month")]):
        ax = axs[i]
        g = tabs[(v, s)].groupby("month")[["r", "r_raw"]].mean()
        ax.plot(g.index, g.r, color=C_ESD, lw=2, marker="o", ms=4, label="다운스케일 (ERA5 격자)")
        ax.plot(g.index, g.r_raw, color=C_RAW, lw=2, marker="o", ms=4, label="원시 1.5° (반경평균)")
        if (v, s) in tabs_asos:
            ga = tabs_asos[(v, s)].groupby("month")[["r"]].mean()
            ax.plot(ga.index, ga.r, color=C_ESD, lw=1.5, ls="--", label="다운스케일 (ASOS 지점)")
        ax.set_xticks(range(1, 13)); ax.set_title(f"{nm[v]} {nm[s]}", loc="left"); ax.set_xlabel("월")
        ax.yaxis.grid(True, color=GRID, lw=0.6); ax.set_ylim(0.3, 1.0)
    axs[0].set_ylabel("교차검증 상관 (점 평균)")
    axs[0].legend(fontsize=7, frameon=False, loc="lower left")
    fig.tight_layout(); fig.savefig(FIG / "fig03_skill_by_month.png"); plt.close(fig)


def fig_model_comparison():
    f = WORK / "model_comparison_asos_month.csv"
    if not f.exists():
        return
    df = pd.read_csv(f)
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, v, nm in zip(axs, ["T", "P"], ["기온", "강수"]):
        g = df[df["var"] == v].groupby("model")["msess"].mean().sort_values()
        col = [C_RAW if k == "Raw(coarse)" else C_ESD for k in g.index]
        ax.barh(g.index, g.values, color=col, height=0.6)
        for y, x in enumerate(g.values):
            ax.text(x + 0.01 if x >= 0 else 0.01, y, f"{x:.2f}", va="center", fontsize=7, color=INK2)
        ax.set_title(f"{nm} 월평균 — ASOS 62지점 MSESS (1·4·7·10월, 8묶음 CV)", loc="left")
        ax.xaxis.grid(True, color=GRID, lw=0.6); ax.axvline(0, color="#c3c2b7", lw=0.8)
    fig.tight_layout(); fig.savefig(FIG / "fig04_model_comparison.png"); plt.close(fig)


def fig_forecast(dsT, dsP, title, fname):
    """블록(주 또는 월)별 기온 편차, 강수 평년비, 기온 3분위 우세확률"""
    nb = dsT.sizes["block"]
    fig, axs = plt.subplots(3, nb, figsize=(2.15 * nb + 1.2, 8.6), squeeze=False)
    lat, lon = dsT.lat.values, dsT.lon.values
    for b in range(nb):
        im1 = field(axs[0, b], dsT.anom.values[b], lat, lon, DIV_T, -3, 3, levels=np.arange(-3, 3.01, 0.5))
        mapax(axs[0, b], str(dsT.block.values[b]))
        im2 = field(axs[1, b], dsP.pct_normal.values[b], dsP.lat.values, dsP.lon.values, DIV_P, 0, 200,
                    levels=[0, 40, 60, 80, 90, 110, 120, 150, 200, 300])
        mapax(axs[1, b])
        pa, pb = dsT.p_above.values[b], dsT.p_below.values[b]
        dom = np.where(pa >= pb, pa, -pb)
        im3 = field(axs[2, b], dom * 100, lat, lon, DIV_T, -100, 100, levels=[-100, -70, -60, -50, -40, 40, 50, 60, 70, 100])
        mapax(axs[2, b])
    fig.colorbar(im1, ax=axs[0], shrink=0.85, label="기온 편차 (°C)")
    fig.colorbar(im2, ax=axs[1], shrink=0.85, label="강수 평년비 (%)")
    cb = fig.colorbar(im3, ax=axs[2], shrink=0.85, label="기온 우세 범주 확률 (%)  -: 낮음, +: 높음")
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, color=INK)
    fig.savefig(FIG / fname, bbox_inches="tight"); plt.close(fig)
