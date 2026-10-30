# 한반도 객관기후예측 (1개월 · 3개월)

호주기상청(BoM) Climate outlooks와 독일기상청(DWD)의 주·월·계절 예측 서비스를 참고해 만든 **한반도 육상 확률 기후전망** 웹 서비스입니다.
ECMWF **EC46**(1개월)·**SEAS5**(3개월) 51개 앙상블 멤버를 [Open-Meteo Seasonal API](https://open-meteo.com/en/docs/seasonal-forecast-api)로 받아
0.5° 격자(육상 118개 지점)에서 확률 산출물을 만들고, 인터랙티브 지도로 보여줍니다.

| 구분 | 1개월 전망 | 3개월 전망 |
|---|---|---|
| 모델 | ECMWF EC46 (매일 갱신) | ECMWF SEAS5 (매월 5일 갱신) |
| 기간 | 1·2·3·4주 + 4주 전체 (월–일, 1주는 발표 다음 주의 그다음 주) | 1·2·3개월 + 3개월 전체 |
| 요소 | 평균기온 · 강수량 · 일사량 · 풍속 | 〃 |
| 표출 | 3분위 확률(우세 범주), 평년(중앙값) 초과확률, 앙상블 평균, 평년편차(평년비), 임계값 초과확률, 상·하위 10% 극한 확률, 앙상블 스프레드 | 〃 |

지도에서 육상 지점을 클릭하면 **별도 창**(끌어서 옮기기·크기 조절·새 브라우저 창 분리)에
일별 앙상블 시계열, 기간별 3분위 확률, 51개 멤버 분포, 임계값별 발생확률 표(CSV 내려받기)가 나옵니다.
설계와 산출 방법은 `site/about.html`(사이트의 「서비스 설계·방법」)에 정리되어 있습니다.

## 구성

```
pipeline/
  config.py        격자·요소·임계값·모델 설정
  build_geo.py     육상 격자(grid.json)와 경계 GeoJSON 생성 (최초 1회, 결과 커밋됨)
  openmeteo.py     Open-Meteo API 클라이언트 (다지점 요청, 재시도, 멤버 파싱)
  climatology.py   ERA5 1991–2020 평년 분포 (캐시 구축·기간별 분위수·IDW 보간)
  outlook.py       전망 산출 → site/data/latest/
  synthetic.py     네트워크 없이 시험하는 합성(DEMO) 자료
site/
  index.html       전망 지도 (Leaflet, 육상 마스킹 필드, 기간 비교)
  point.html       지점 상세 창 (시계열·분포·통계표)
  about.html       서비스 설계·방법
.github/workflows/
  outlook.yml      매일 07:10 KST 산출 → outlook-data 브랜치 저장 + GitHub Pages 배포
  climatology.yml  ERA5 평년값 캐시 구축 (호출 한도 시 다음 날 이어받기)
```

## 실행

```bash
pip install -r pipeline/requirements.txt
python pipeline/climatology.py      # ERA5 평년 캐시 (최초 1회, 중단되면 다시 실행해 이어받기)
python pipeline/outlook.py          # 실자료 산출  (--demo: 합성 자료)
python -m http.server -d site 8000  # http://localhost:8000
```

저장소에 들어 있는 `site/data/latest/`는 **DEMO(합성) 자료**입니다. 실제 전망은 GitHub Actions가 매일 만들어
`gh-pages` 브랜치에 웹사이트째 올립니다. 저장소 **Settings → (왼쪽 메뉴) Pages → Build and deployment → Source: Deploy from a branch → Branch: `gh-pages` / `(root)` → Save** 로 설정하면 `https://nalssi89.github.io/objective_climate_outlook/` 에서 열립니다.

## 지역 상세화 (기상청 ASOS)

- **ASOS 지점 상세화:** 기상청 공식 평년 지점 66곳(남한 본토 대표 62곳 + 제주 4곳, 대구·전주는 공식 병합 지점 860·864 자료)의 1991–2020 관측으로 평년 분포를 만든다. 평년 범위는 기상청 방식대로 기온은 평년 ± 0.43σ(표본표준편차), 강수·일사·풍속은 33–67 백분위다. 주변 모델 격자의 멤버별 평년편차(기온)·평년비(강수·일사·풍속)를 지점으로 보간해 그 분포에 적용한다. 지도에는 지점 원으로 표시되고, 클릭하면 지점 상세 창이 열린다.
- **달력 월(3개월 전망의 1·2·3개월)은 기상청 공식 범위:** 지점·20 km 격자의 평년값은 기상청 공식 월평년값(API 허브 `sfc_norm1.php`, 1991–2020)을 쓴다. 지도 위에는 남한 본토 62개 지점 평균을 공식 월평년 '비슷' 범위(기온 평년 ± 0.43σ, 강수 33–67 백분위; kmahub 기준표)로 3분류한 확률을 따로 보여 준다.
- **남한 20 km(0.2°) 상세화:** 지점 관측 평년과 분포를 271개 격자로 보간한다(기온은 기온감률 6.5 °C/km로 고도 보정, 격자 평균 고도는 Open-Meteo Elevation 25표본). 같은 방식으로 모델 신호를 적용한다. 북한은 0.5° 모델 격자를 유지한다.
- 수집: `KMA_APIHUB_KEY`(저장소 Secret) → `python pipeline/asos.py`(이어받기) · `python pipeline/fine_grid.py elev`. GitHub Actions 「ASOS 관측 평년 구축」이 수행한다.

## 자동 갱신

- **매일 07:10 KST**(22:10 UTC) GitHub Actions가 최신 EC46·SEAS5를 받아 다시 산출·게시합니다. GitHub 예약 실행은 지연·누락될 수 있어 08:40·12:10 KST에도 걸어 두었고, 그날 07시 이후 발표가 이미 있으면 건너뜁니다.
- 1개월 전망(EC46)은 매일 새 예측이 나오고, 3개월 전망(SEAS5)은 매월 5일에 바뀝니다.
- 매일 발표분 지도 자료는 45일간 보관되어, 지도 왼쪽 **발표일** 목록에서 지난 발표를 골라 같은 주간의 예측이 어떻게 바뀌어 왔는지 비교할 수 있습니다.
- 마지막 발표가 30시간을 넘기면 화면 상단에 '갱신 지연'이 표시됩니다.
- 수동 실행: 저장소 **Actions → 객관기후예측 갱신 → Run workflow**.
- 공개 저장소에서 60일 동안 활동(커밋)이 없으면 GitHub가 예약 실행을 멈춥니다. 그럴 때는 Actions 화면의 안내에 따라 다시 켜면 됩니다.

## 방법 요약

1. 멤버별 일별값을 주·월·계절로 집계(강수 누적, 그 밖에는 평균)
2. ECMWF가 재예측으로 계산한 편차를 이용해 **모델 평년값**을 역산 → 모델 계통오차 제거
   (3개월: SEAS5 월별 편차, 기온 가법·그 밖에는 승법 / 1개월: 기온은 EC46 주별 편차, 강수·일사·풍속은 SEAS5 월별 모델 기후를 일 단위로 환산)
3. ERA5 1991–2020 같은 달력기간 분포에서 분위수 형태(10/33/50/67/90%)를 가져와 모델 평년값에 적용
4. 51개 멤버 중 각 조건(하위·상위 1/3, 중앙값, 상·하위 10%, 임계값)을 만족하는 비율 = 확률

자료: ECMWF (EC46, SEAS5, ERA5) via Open-Meteo (CC BY 4.0, 비상업 무료 API) · Natural Earth.
편의·신뢰도 보정 전의 실험적 서비스이며 공식 예보가 아닙니다.
