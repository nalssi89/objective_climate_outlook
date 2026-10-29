"""데모용 합성 자료 — Open-Meteo 응답과 같은 구조를 만들어 파이프라인 전체를 오프라인으로 시험한다.

실제 예측값이 아니다. (site 화면에 'DEMO' 로 표시됨)
"""
import datetime as dt

import numpy as np

from climatology import DAY0, Climatology, clim_points
from config import CLIM_YEARS, VARIABLES

RNG = np.random.default_rng(20261029)


def _normal(var, lat, lon, doy):
    """위도·계절에 따른 대략적 한반도 평년값."""
    w = 2 * np.pi / 365.25
    if var == "temperature_2m_mean":
        tm = 14.5 - 1.1 * (lat - 35) - 0.25 * np.maximum(lon - 127.5, 0) * (lat > 37)
        amp = 11 + 0.9 * (lat - 35)
        return tm + amp * np.cos(w * (doy - 205))
    if var == "precipitation_sum":
        ann = 1350 - 75 * (lat - 35)
        f = 0.35 + 2.4 * np.exp(-(((doy - 200) / 32.0) ** 2))
        return ann / 365.25 * f / 0.88
    if var == "shortwave_radiation_sum":
        clr = 15 + 8.5 * np.cos(w * (doy - 172)) - 0.25 * (lat - 36)
        monsoon = 1 - 0.25 * np.exp(-(((doy - 195) / 25.0) ** 2))
        return clr * monsoon
    if var == "wind_speed_10m_mean":
        coast = 0.8 if (lon > 128.8 or lon < 126.3 or lat < 34.8) else 0.0
        return 2.6 + coast + 0.7 * np.cos(w * (doy - 40))
    raise KeyError(var)


def _daily_noise(var, n, size):
    if var == "temperature_2m_mean":
        e = np.zeros(size + (n,))
        z = RNG.normal(0, 1, size + (n,))
        for t in range(n):
            e[..., t] = (0.8 * e[..., t - 1] if t else 0) + 1.6 * z[..., t]
        return e, "add"
    if var == "precipitation_sum":
        return RNG.gamma(0.35, 1 / 0.35, size + (n,)) * (RNG.random(size + (n,)) < 0.95), "mul"
    sd = 0.25 if var == "shortwave_radiation_sum" else 0.22
    return np.clip(RNG.normal(1, sd, size + (n,)), 0.15, 2.2), "mul"


def climatology():
    pts = clim_points()
    ndays = (dt.date(CLIM_YEARS[1], 12, 31) - DAY0).days + 1
    dates = [DAY0 + dt.timedelta(days=i) for i in range(ndays)]
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    data = {}
    for k, V in VARIABLES.items():
        var = V["era5"]
        base = np.array([_normal(var, la, lo, doy) for la, lo in pts])
        noise, mode = _daily_noise(var, ndays, (1,))
        # 공간적으로 상관된 잡음(한 장 공유) + 연간 변동
        yearly = RNG.normal(0, 1, CLIM_YEARS[1] - CLIM_YEARS[0] + 1)
        yidx = np.array([d.year - CLIM_YEARS[0] for d in dates])
        if mode == "add":
            data[k] = (base + noise + 0.7 * yearly[yidx]).astype(np.float32)
        else:
            data[k] = (base * noise * np.exp(0.12 * yearly[yidx])).astype(np.float32)
    return Climatology(pts, dates, data)


def seasonal(points, key, issue, forecast_days, daily_vars, weekly, monthly, nmem=51):
    start = issue
    dates = [start + dt.timedelta(days=i) for i in range(forecast_days)]
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
    n = len(dates)
    bias = {"temperature_2m_mean": 0.8, "precipitation_sum": 1.15, "shortwave_radiation_sum": 0.92, "wind_speed_10m_mean": 1.2}
    out = []
    for la, lo in points:
        # 예측 신호: 남동쪽이 더 따뜻·습윤, 시간에 따라 서서히 약화
        decay = np.exp(-np.arange(n) / 70)
        sig_t = (0.4 + 0.25 * (37 - la) + 0.15 * (lo - 127)) * decay + 0.3
        sig_p = np.exp((0.25 + 0.06 * (36.5 - la)) * decay)
        daily = {"time": [d.isoformat() for d in dates]}
        series = {}
        for var in daily_vars:
            normal = _normal(var, la, lo, doy)
            noise, mode = _daily_noise(var, n, (nmem,))
            if var == "temperature_2m_mean":
                v = normal + bias[var] + sig_t + noise + RNG.normal(0, 0.6, (nmem, 1))
            elif var == "precipitation_sum":
                v = normal * bias[var] * sig_p * noise * np.exp(RNG.normal(0, 0.25, (nmem, 1)))
            elif var == "shortwave_radiation_sum":
                v = normal * bias[var] / np.sqrt(sig_p) * noise
            else:
                v = normal * bias[var] * noise
            v = np.round(v, 2)
            series[var] = (v, normal)
            daily[var] = v[0].tolist()
            for m in range(1, nmem):
                daily[f"{var}_member{m:02d}"] = v[m].tolist()
        r = {"latitude": la, "longitude": lo, "daily": daily}

        def model_clim(var):
            v, normal = series[var]
            return normal + bias[var] if var == "temperature_2m_mean" else normal * bias[var]

        if weekly:
            ws = issue + dt.timedelta(days=(7 - issue.weekday()) % 7 or 7)
            wk = {"time": []}
            for k in range(5):
                s = ws + dt.timedelta(days=7 * k)
                i0 = (s - start).days
                if i0 + 7 > n:
                    break
                wk["time"].append(s.isoformat())
                for V in VARIABLES.values():
                    if not V["weekly"]:
                        continue
                    v, _ = series[V["daily"]]
                    ens = v[:, i0:i0 + 7].mean()
                    cl = model_clim(V["daily"])[i0:i0 + 7].mean()
                    wk.setdefault(V["weekly"] + "_mean", []).append(round(float(ens), 2))
                    wk.setdefault(V["weekly"] + "_anomaly", []).append(round(float(ens - cl), 2))
                tv = series["temperature_2m_mean"][0][:, i0:i0 + 7].mean(axis=1) - model_clim("temperature_2m_mean")[i0:i0 + 7].mean()
                pv = (series["precipitation_sum"][0][:, i0:i0 + 7].sum(axis=1) - model_clim("precipitation_sum")[i0:i0 + 7].sum())
                for name, val in (("temperature_2m_anomaly_gt0", tv > 0), ("temperature_2m_anomaly_gt1", tv > 1),
                                  ("temperature_2m_anomaly_gt2", tv > 2), ("temperature_2m_anomaly_ltm1", tv < -1),
                                  ("temperature_2m_anomaly_ltm2", tv < -2), ("precipitation_anomaly_gt0", pv > 0),
                                  ("precipitation_anomaly_gt10", pv > 10), ("precipitation_anomaly_gt20", pv > 20)):
                    wk.setdefault(name, []).append(round(100 * float(val.mean())))
                wk.setdefault("temperature_2m_efi", []).append(round(float(np.tanh(tv.mean() / 2)), 2))
                wk.setdefault("precipitation_efi", []).append(round(float(np.tanh(pv.mean() / 30)), 2))
            r["weekly"] = wk
        if monthly:
            mo = {"time": []}
            y, m = issue.year, issue.month
            for k in range(5):
                mm0 = m - 1 + k
                s = dt.date(y + mm0 // 12, mm0 % 12 + 1, 1)
                mm1 = mm0 + 1
                e = dt.date(y + mm1 // 12, mm1 % 12 + 1, 1)
                i0, i1 = max((s - start).days, 0), (e - start).days
                if i1 > n:
                    break
                mo["time"].append(s.isoformat()[:7])
                for V in VARIABLES.values():
                    v, _ = series[V["daily"]]
                    ens = v[:, i0:i1].mean()  # 월평균(일 단위) — 단위가 달라도 비율 방식으로 처리됨
                    cl = model_clim(V["daily"])[i0:i1].mean()
                    mo.setdefault(V["monthly"] + "_mean", []).append(round(float(ens), 3))
                    mo.setdefault(V["monthly"] + "_anomaly", []).append(round(float(ens - cl), 3))
            r["monthly"] = mo
        out.append(r)
    return out
