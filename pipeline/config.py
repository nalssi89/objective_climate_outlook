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
    "1m": {"name": "1개월 전망", "model": "ecmwf_ec46", "model_name": "ECMWF EC46 (51 멤버)", "forecast_days": 46},
    "3m": {"name": "3개월 전망", "model": "ecmwf_seas5", "model_name": "ECMWF SEAS5 (51 멤버)", "forecast_days": 130},
}

# 기상청 공식 평년 지점 66곳 = 남한 본토 대표 62곳 + 제주 4곳 (kmahub normalCriteria.js 기준)
ASOS_OFFICIAL_66 = [
    108, 112, 119, 201, 202, 203,
    90, 105, 100, 216,
    211, 95, 101, 212, 114,
    131, 127, 226, 135, 221,
    133, 232, 129, 235, 236, 238,
    143, 281, 138, 279, 278, 136, 273, 272, 277, 130, 271,
    159, 152, 284, 285, 289, 288, 295, 192, 155, 162, 294,
    146, 243, 245, 140, 247, 244, 248,
    156, 165, 261, 260, 170, 262, 168,
    184, 185, 188, 189,
]
# 공식 평년은 이전 관측소 자료를 이어 붙인 병합 지점을 쓴다: 대구 143 → 860(신암), 전주 146 → 864(완산)
ASOS_MERGE = [
    {"station": 143, "source": 860, "from": "2015-06-12", "name": "대구(신암)"},
    {"station": 146, "source": 864, "from": "2015-07-01", "name": "전주(완산)"},
]
# 기온 평년 범위: 기상청 방식(평년 ± 0.43σ, 표본표준편차). 강수 등은 33–67 백분위
TEMP_TERCILE_SIGMA = 0.43

# 기상청 공식 남한(본토 62개 지점 평균) 1991–2020 월평년값과 '비슷' 범위 (kmahub src/normalCriteria.js)
#  기온: 평년 ± halfRange(=0.43σ, 5일 이동평균 기반), 강수: 33–67 백분위 [lower, upper]
KOREA_OFFICIAL_MONTHLY = {
    "t2m": {
        "normal": [-0.9, 1.2, 6.1, 12.1, 17.3, 21.4, 24.6, 25.1, 20.5, 14.3, 7.6, 1.1],
        "half": [0.6, 0.6, 0.5, 0.5, 0.3, 0.3, 0.6, 0.5, 0.3, 0.4, 0.6, 0.6],
    },
    "precip": {
        "normal": [26.2, 35.7, 56.5, 89.7, 102.1, 148.2, 296.5, 282.6, 155.1, 63.0, 48.0, 28.0],
        "lower": [17.4, 27.5, 42.7, 70.3, 79.3, 101.6, 245.9, 225.3, 84.2, 37.0, 30.7, 19.8],
        "upper": [26.8, 44.9, 58.5, 99.3, 125.5, 174.0, 308.2, 346.7, 202.3, 64.3, 55.1, 28.6],
    },
}
KOREA_MAINLAND_62 = [s for s in ASOS_OFFICIAL_66 if s not in (184, 185, 188, 189)]
