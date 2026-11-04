"""PyESD Regressors 비교 (ASOS 62지점 중 16지점, 월평균): 같은 예측인자(EOF PC + 반경평균)로 모형만 바꿔
8개 연도 묶음 교차검증 상관·MSESS를 비교한다. 대표월 1·4·7·10월.
PyESD 1.0.7은 scikit-learn 1.9와 맞지 않아(ARD n_iter 등) 같은 설정을 sklearn으로 직접 구성했다.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import esd, train
from sklearn.linear_model import RidgeCV, LassoCV, ARDRegression, BayesianRidge
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor, StackingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.svm import SVR
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor
warnings.filterwarnings("ignore")

STNS = list(range(0, 62, 4))   # 계산량 때문에 16개 지점(4개마다 1개)으로 비교
MODELS = {
    "RidgeCV": lambda: RidgeCV(alphas=[1e-2, 1e-1, 1, 10, 100]),
    "LassoCV": lambda: LassoCV(cv=5, max_iter=5000),
    "ARD": lambda: ARDRegression(max_iter=500),
    "BayesianRidge": lambda: BayesianRidge(max_iter=500),
    "RandomForest": lambda: RandomForestRegressor(n_estimators=100, min_samples_leaf=3, n_jobs=2, random_state=42),
    "XGBoost": lambda: XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.05, subsample=0.8, n_jobs=2, random_state=42),
    "SVR": lambda: make_pipeline(StandardScaler(), SVR(C=1.0, gamma="scale")),
    "MLP": lambda: make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(50,), alpha=1.0, max_iter=2000, random_state=42)),
    "Stacking": lambda: StackingRegressor([("ridge", RidgeCV(alphas=[1e-1, 1, 10, 100])),
                                           ("rf", RandomForestRegressor(n_estimators=100, min_samples_leaf=3, n_jobs=2, random_state=42)),
                                           ("xgb", XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.05, n_jobs=2))],
                                          final_estimator=RidgeCV(), cv=3),
}


def main(var):
    D = train.prepare("asos", var, "month")
    ya = D["ya"]; times = ya.time.to_index(); yrs = times.year.values; Y = ya.values
    Xall = {v: D["X"][v].values for v in esd.PVARS}
    rows = []
    for m in (1, 4, 7, 10):
        win = esd.season_window(times, m, 1) & (yrs <= 2022)
        sub = lambda mask: {v: Xall[v][mask] for v in esd.PVARS}
        ug = np.arange(1991, 2023); folds = np.array_split(ug, 8)
        pred = {k: np.full((len(times), Y.shape[1]), np.nan) for k in list(MODELS) + ["Raw(coarse)"]}
        for f in folds:
            fit, te = win & ~np.isin(yrs, f), win & np.isin(yrs, f) & (times.month.values == m)
            e = esd.EOFPredictors(train.NPC["month"]).fit(sub(fit))
            PCf, PCt = e.transform(sub(fit)), e.transform(sub(te))
            Lf, Lt = train.local_feats(sub(fit), D["W"], var), train.local_feats(sub(te), D["W"], var)
            pred["Raw(coarse)"][te] = Lt[:, 0, :]
            for j in STNS:
                Xf, Xt = np.column_stack([PCf, Lf[:, :, j]]), np.column_stack([PCt, Lt[:, :, j]])
                ok = np.isfinite(Y[fit, j])
                for k, mk in MODELS.items():
                    pred[k][te, j] = mk().fit(Xf[ok], Y[fit, j][ok]).predict(Xt)
        cen = (times.month.values == m) & (yrs <= 2022)
        for k, p in pred.items():
            for j in STNS:
                o, q = Y[cen, j], p[cen, j]; ok = np.isfinite(o) & np.isfinite(q)
                rows.append(dict(var=var, month=m, model=k, stn=j, r=np.corrcoef(o[ok], q[ok])[0, 1],
                                 msess=1 - np.mean((o[ok] - q[ok]) ** 2) / np.mean(o[ok] ** 2)))
        print(var, m, flush=True)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "work")
    df = pd.concat([main("T"), main("P")])
    df.to_csv(out / "model_comparison_asos_month.csv", index=False)
    print(df.groupby(["var", "model"])[["r", "msess"]].mean().round(3))
