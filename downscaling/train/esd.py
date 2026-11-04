"""PyESD 방식의 Perfect-Prognosis 통계 다운스케일링 핵심 모듈 (scikit-learn 1.9 호환으로 재구성).

PyESD 구성요소와의 대응
  RegionalAverage(반경 평균)      -> local_features(): 대상점 주변 반경 R km 안 1.5도 격자점 가중평균
  teleconnection EOF 지수           -> EOFPredictors : 동아시아 영역 변수별 EOF 주성분
  MonthlyStandardizer               -> 일별 조화함수 기후값 제거 + 계절창별 표준화
  feature selection / Regressors    -> RidgeCV(기본), 지점 비교는 compare_models.py
  cross_validate_and_predict        -> 연도 블록 교차검증(leave-one-year-out)

시간 단위: 'week'(7일 평균, 매일 시작) / 'month'(달력월 평균)
변수: T(일평균기온, °C), P(강수, sqrt(mm/일) 공간에서 적합 후 역변환)
"""
import numpy as np, pandas as pd, xarray as xr

CLIM = ("1991-01-01", "2020-12-31")
PVARS = ["t2m", "d2m", "msl", "tp"]


# ---------------------------------------------------------------- 시간 집계·기후값
def aggregate(da, scale):
    """일자료 -> 7일 이동평균(끝점 기준 정렬을 중심으로) 또는 월평균."""
    if scale == "week":
        x = da.rolling(time=7, center=True, min_periods=6).mean()
        return x
    return da.resample(time="MS").mean()


def transform(da, var):
    return np.sqrt(da.clip(min=0)) if var in ("P", "tp") else da


def harmonic_clim(da, nh=4):
    """1991~2020 일별 기후값: 평균 + nh개 조화함수 최소제곱 (MonthlyStandardizer의 일 단위 확장)."""
    c = da.sel(time=slice(*CLIM))
    t = c.time.dt.dayofyear.values
    def basis(tt):
        w = 2 * np.pi * tt / 365.25
        return np.column_stack([np.ones_like(w)] + [f(k * w) for k in range(1, nh + 1) for f in (np.sin, np.cos)])
    B = basis(t)
    y = c.values.reshape(len(t), -1)
    ok = np.isfinite(y)
    coef = np.full((B.shape[1], y.shape[1]), np.nan)
    for j in range(y.shape[1]):
        if ok[:, j].sum() > 100:
            coef[:, j] = np.linalg.lstsq(B[ok[:, j]], y[ok[:, j], j], rcond=None)[0]
    return coef, basis


def anomalies(da, scale):
    """집계 후 기후값 편차. 반환: (편차, 기후값 함수 clim(doy 또는 month) -> 값)"""
    if scale == "week":
        coef, basis = harmonic_clim(da)
        shp = da.shape[1:]
        clim_fn = lambda doy: (basis(np.atleast_1d(doy)) @ coef).reshape((-1,) + shp)
        cl = clim_fn(da.time.dt.dayofyear.values)
        return da - cl, clim_fn
    mclim = da.sel(time=slice(*CLIM)).groupby("time.month").mean()
    clim_fn = lambda month: mclim.sel(month=np.atleast_1d(month)).values
    return da.groupby("time.month") - mclim, clim_fn


# ---------------------------------------------------------------- 예측인자
def season_window(times, month, half=1):
    m = pd.DatetimeIndex(times).month
    d = (m - month + 6) % 12 - 6
    return np.abs(d) <= half


class EOFPredictors:
    """변수별 표준화 편차장의 EOF -> 주성분 (PyESD teleconnections.eof_analysis의 역할)."""

    def __init__(self, n_per_var=6):
        self.n = n_per_var

    def fit(self, fields):          # fields: dict var -> (n, npts)
        self.mu, self.sd, self.eof = {}, {}, {}
        for v, X in fields.items():
            self.mu[v] = np.nanmean(X, 0); self.sd[v] = np.nanstd(X, 0) + 1e-6
            Z = np.nan_to_num((X - self.mu[v]) / self.sd[v])
            U, S, Vt = np.linalg.svd(Z, full_matrices=False)
            self.eof[v] = Vt[:self.n]
            self.pcsd = getattr(self, "pcsd", {}); self.pcsd[v] = (Z @ Vt[:self.n].T).std(0) + 1e-9
            self.evr = getattr(self, "evr", {}); self.evr[v] = (S[:self.n] ** 2 / (S ** 2).sum())
        return self

    def transform(self, fields):
        out = [np.nan_to_num((fields[v] - self.mu[v]) / self.sd[v]) @ self.eof[v].T / self.pcsd[v]
               for v in self.eof]
        return np.concatenate(out, 1)


def radius_weights(plat, plon, tlat, tlon, radius=250.0):
    """대상점(tlat,tlon)마다 반경 내 예측인자 격자점 가중치 (PyESD RegionalAverage, 가우스 가중)."""
    R = 6371.0
    la1, lo1 = np.deg2rad(tlat)[:, None], np.deg2rad(tlon)[:, None]
    la2, lo2 = np.deg2rad(plat)[None], np.deg2rad(plon)[None]
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    d = 2 * R * np.arcsin(np.sqrt(a))
    w = np.exp(-(d / radius) ** 2) * (d <= 2 * radius)
    w[w.sum(1) == 0, np.argmin(d[w.sum(1) == 0], 1) if (w.sum(1) == 0).any() else []] = 1.0
    return w / w.sum(1, keepdims=True)


# ---------------------------------------------------------------- 회귀 (점별 능형회귀, 공통 PC + 지역평균)
def design(PC, L):
    """(npt, n, p) 설계행렬: [공통 PC | 점별 지역평균 인자 | 1]"""
    n, npt = PC.shape[0], L.shape[2]
    return np.concatenate([np.broadcast_to(PC[None], (npt,) + PC.shape),
                           np.transpose(L, (2, 0, 1)), np.ones((npt, n, 1))], 2)


def _ridge_batch(X, Y, W, a):
    """X (npt,n,p), Y (npt,n), W (npt,n) 0/1 가중, a (npt,) -> coef (npt,p)"""
    p = X.shape[2]
    # 열 표준화(가중 표준편차): 단위가 다른 지역평균 인자(sqrt mm, hPa, °C)가 벌점을 고르게 받도록
    nw = W.sum(1, keepdims=True)[..., None] + 1e-9
    mu = (X * W[..., None]).sum(1, keepdims=True) / nw
    sd = np.sqrt((((X - mu) ** 2) * W[..., None]).sum(1, keepdims=True) / nw)
    sd[..., -1] = 1.0; sd = np.where(sd < 1e-9, 1.0, sd)
    X = X / sd
    Xw = X * W[..., None]
    G = np.matmul(Xw.transpose(0, 2, 1), X)
    b = np.matmul(Xw.transpose(0, 2, 1), Y[..., None])[..., 0]
    P = np.eye(p)[None] * np.asarray(a)[:, None, None]; P[:, -1, -1] = 0.0
    return np.linalg.solve(G + P, b[..., None])[..., 0] / sd[:, 0, :]


def fit_points(PC, L, Y, alphas=(1.0, 10.0, 100.0, 1000.0), groups=None, alpha=None):
    """점별 능형회귀 (모든 점을 한 번에). alpha가 없으면 연도 5-묶음 CV로 점별 선택.
    반환 coef (npt,p), alpha (npt,)"""
    X = design(PC, L)
    Yt = Y.T.copy()
    W = (np.isfinite(Yt) & np.isfinite(X).all(2)).astype(float)
    X = np.nan_to_num(X); Yt = np.nan_to_num(Yt)
    npt = Yt.shape[0]
    if alpha is None:
        ug = np.unique(groups); folds = np.array_split(ug, 5)
        err = np.zeros((len(alphas), npt))
        for ia, a in enumerate(alphas):
            for f in folds:
                te = np.isin(groups, f)
                Wtr = W * (~te)[None]
                c = _ridge_batch(X, Yt, Wtr, np.full(npt, a))
                r = (np.matmul(X, c[..., None])[..., 0] - Yt) * W * te[None]
                err[ia] += (r ** 2).sum(1)
        alpha = np.asarray(alphas)[err.argmin(0)]
    alpha = np.broadcast_to(np.asarray(alpha, float), (npt,)).copy()
    return _ridge_batch(X, Yt, W, alpha), alpha


def predict_points(coefs, PC, L):
    return np.matmul(design(PC, L), coefs[..., None])[..., 0].T
