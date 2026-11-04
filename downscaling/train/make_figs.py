"""교차검증·독립검증 기술 표와 그림 생성."""
import os
import sys
from pathlib import Path
import numpy as np, pandas as pd, xarray as xr
sys.path.insert(0, str(Path(__file__).parent))
import plots, apply
from plots import plt, field, mapax, DIV_T, DIV_P, INK

TAB = Path(os.environ.get("KDS_TAB", "../docs")); TAB.mkdir(exist_ok=True, parents=True)
combos = [("T", "week"), ("T", "month"), ("P", "week"), ("P", "month")]


def main():
    tabs, tabs_a, summ = {}, {}, []
    for v, s in combos:
        for kind, store in (("grid", tabs), ("asos", tabs_a)):
            f = plots.WORK / f"cv_{kind}_{v}_{s}.nc"
            if not f.exists():
                continue
            cvt = plots.skill_table(kind, v, s)
            tst = plots.skill_table(kind, v, s, period=(2023, 2026), pooled=True)
            cvp = plots.skill_table(kind, v, s, pooled=True)
            store[(v, s)] = cvt
            cvt.to_csv(TAB / f"skill_cv_{kind}_{v}_{s}.csv", index=False)
            for nm, d in (("CV 1991-2022 (달별 평균)", cvt), ("CV 1991-2022 (전체)", cvp), ("독립 2023-2026 (전체)", tst)):
                summ.append(dict(대상=kind, 변수=v, 단위=s, 기간=nm, 상관=d.r.mean(), MSESS=d.msess.mean(),
                                 상관_원시=d.r_raw.mean(), MSESS_원시=d.msess_raw.mean()))
    pd.DataFrame(summ).round(3).to_csv(TAB / "skill_summary.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(summ).round(3).to_string())
    if len(tabs) == 4:
        plots.fig_skill_maps(tabs)
    plots.fig_skill_month(tabs, tabs_a)
    plots.fig_model_comparison()
    fig_pp2026()


def fig_pp2026():
    """2026년 독립 점검: ERA5 예측인자를 '완벽 예보'로 넣은 월 상세예측 vs ERA5 0.25° 관측."""
    fc = apply.era5_as_forecast("2026-01-01", 300)
    dT, dP = apply.downscale(fc, "grid", "T", "month"), apply.downscale(fc, "grid", "P", "month")
    cvT = xr.open_dataset(plots.WORK / "cv_grid_T_month.nc").sel(time=slice("2026-01", "2026-09"))
    cvP = xr.open_dataset(plots.WORK / "cv_grid_P_month.nc").sel(time=slice("2026-01", "2026-09"))
    sel = [0, 6, 7, 8]
    fig, axs = plt.subplots(4, len(sel), figsize=(2.3 * len(sel) + 1, 10.6))
    lat, lon = dT.lat.values, dT.lon.values
    for i, b in enumerate(sel):
        oT, pT = cvT.obs.values[b], dT.anom.values[b]
        obsP = np.clip(cvP.clim_sqrt.values[b] + cvP.obs.values[b], 0, None) ** 2
        oP = 100 * obsP / np.maximum(dP.normal.values[b], .05)
        lv = np.arange(-3, 3.01, 0.5); lp = [0, 40, 60, 80, 90, 110, 120, 150, 200, 300]
        a = field(axs[0, i], oT, lat, lon, DIV_T, -3, 3, lv); mapax(axs[0, i], f"{dT.block.values[b]} 관측(ERA5)")
        field(axs[1, i], pT, lat, lon, DIV_T, -3, 3, lv); mapax(axs[1, i], f"상세예측 r={np.corrcoef(oT, pT)[0,1]:.2f}")
        c = field(axs[2, i], oP, lat, lon, DIV_P, 0, 200, lp); mapax(axs[2, i], "강수 평년비 관측")
        q = dP.pct_normal.values[b]
        field(axs[3, i], q, lat, lon, DIV_P, 0, 200, lp); mapax(axs[3, i], f"상세예측 r={np.corrcoef(oP, q)[0,1]:.2f}")
    fig.colorbar(a, ax=axs[:2], shrink=0.8, label="기온 편차 (°C)")
    fig.colorbar(c, ax=axs[2:], shrink=0.8, label="강수 평년비 (%)")
    fig.suptitle("2026년 독립 점검 — 재분석 대규모장 입력 시 한반도 상세 재현", x=0.01, ha="left", fontsize=12, color=INK)
    fig.savefig(plots.FIG / "fig05_pp_check_2026.png", bbox_inches="tight"); plt.close(fig)


if __name__ == "__main__":
    main()
