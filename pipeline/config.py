"""객관기후예측 파이프라인 설정."""

# 분석 격자 (모델 해상도 36 km 와 비슷한 0.5°)
GRID = {"lat0": 33.0, "lat1": 43.0, "lon0": 124.0, "lon1": 131.0, "step": 0.5}

SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "Asia/Seoul"

# 평년 기준 기간 (ERA5 재분석, WMO 표준 평년)
CLIM_YEARS = (1991, 2020)
# 평년 분포(분위수)를 계산할 ERA5 대표 지점 (0.5° 격자 위). 분포의 '형태'는 공간적으로 완만하므로
# Open-Meteo 무료 호출 한도(일 10,000 가중치)를 고려해 권역별 12개 지점만 사용하고 격자로 IDW 보간한다.
CLIM_POINTS = [
    (42.0, 129.5), (41.0, 127.0), (40.0, 125.0), (40.0, 127.5), (39.0, 126.0), (38.5, 127.5),
    (37.5, 127.0), (37.5, 129.0), (36.5, 127.5), (35.5, 128.5), (35.0, 126.5), (33.5, 126.5),
]
CLIM_CHUNK_YEARS = 5  # 한 번에 받는 기간(호출 가중치 분산)

# 요소 정의
#  daily  : Open-Meteo 일별 변수 (앙상블 멤버 포함)
#  era5   : ERA5(archive API) 일별 변수
#  agg    : 기간 집계 방식 (sum=누적, mean=평균)
#  mode   : 평년편차 방식 (add=차이, mul=비율)
#  weekly/monthly : ECMWF 가 직접 계산한 주/월 평균·편차 변수 접두어 (모델 기후값 기준)
VARIABLES = {
    "t2m": {
        "name": "평균기온", "unit": "°C", "daily": "temperature_2m_mean", "era5": "temperature_2m_mean",
        "agg": "mean", "mode": "add", "weekly": "temperature_2m", "monthly": "temperature_2m",
        "thresholds": {"anom": [-2, -1, 1, 2]},
    },
    "precip": {
        "name": "강수량", "unit": "mm", "daily": "precipitation_sum", "era5": "precipitation_sum",
        "agg": "sum", "mode": "mul", "weekly": "precipitation", "monthly": "precipitation",
        "thresholds": {"ratio": [50, 150, 200],
                       "abs": {"week": [10, 30, 50, 100], "month": [50, 100, 200, 300], "season": [100, 300, 500, 800]}},
    },
    "rad": {
        "name": "일사량", "unit": "MJ/m²/일", "daily": "shortwave_radiation_sum", "era5": "shortwave_radiation_sum",
        "agg": "mean", "mode": "mul", "weekly": None, "monthly": "shortwave_radiation",
        "thresholds": {"ratio": [80, 90, 110, 120]},
    },
    "wind": {
        "name": "풍속", "unit": "m/s", "daily": "wind_speed_10m_mean", "era5": "wind_speed_10m_mean",
        "agg": "mean", "mode": "mul", "weekly": "wind_speed_10m", "monthly": "wind_speed_10m",
        "thresholds": {"ratio": [80, 90, 110, 120]},
    },
}

# EC46 가 직접 제공하는 주별 편차 확률(100 멤버, 모델 기후 기준)
EC46_WEEKLY_PROBS = [
    "temperature_2m_anomaly_gt0", "temperature_2m_anomaly_gt1", "temperature_2m_anomaly_gt2",
    "temperature_2m_anomaly_ltm1", "temperature_2m_anomaly_ltm2",
    "precipitation_anomaly_gt0", "precipitation_anomaly_gt10", "precipitation_anomaly_gt20",
    "temperature_2m_efi", "precipitation_efi",
]

# ERA5 평년 분포가 없을 때 쓰는 기본 변동폭 (기간 길이별 표준편차; add=°C, mul=변동계수)
DEFAULT_SPREAD = {
    "t2m": {"week": 1.8, "month": 1.1, "season": 0.8},
    "precip": {"week": 0.9, "month": 0.55, "season": 0.35},
    "rad": {"week": 0.15, "month": 0.08, "season": 0.06},
    "wind": {"week": 0.18, "month": 0.10, "season": 0.07},
}

PRODUCTS = {
    "1m": {"name": "1개월 전망", "model": "ecmwf_ec46", "model_name": "ECMWF EC46 (51 멤버)", "forecast_days": 42},
    "3m": {"name": "3개월 전망", "model": "ecmwf_seas5", "model_name": "ECMWF SEAS5 (51 멤버)", "forecast_days": 130},
}
