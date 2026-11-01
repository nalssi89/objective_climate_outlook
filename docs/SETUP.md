# 다른 곳에 구축하기

이 저장소는 서버 없이 **GitHub Actions(계산) + GitHub Pages(웹)** 만으로 돌아갑니다.
평년 자료 캐시(ERA5, ASOS, 기상청 공식 월평년값, 상세 격자 고도)가 저장소에 들어 있어서,
복사한 저장소에서는 첫 실행부터 바로 실자료 전망을 만들 수 있습니다.

## 1. GitHub 에서 그대로 운영 (권장)

1. **저장소 복사**
   - 이 저장소를 Fork 하거나, 새 저장소를 만들고 전체를 push 합니다.
     ```bash
     git clone https://github.com/nalssi89/objective_climate_outlook.git
     cd objective_climate_outlook
     git remote set-url origin https://github.com/<내 계정>/<새 저장소>.git
     git push -u origin --all
     ```
   - 예약 실행(schedule)은 **기본 브랜치**에서만 돌아갑니다. 작업 브랜치를 기본 브랜치로 지정하거나 `main` 으로 합치세요.
2. **Actions 권한**
   - Settings → Actions → General → Workflow permissions → **Read and write permissions** (gh-pages 브랜치 게시와 캐시 커밋에 필요).
   - Fork 한 경우 Actions 탭에서 워크플로 사용을 한 번 켭니다.
3. **기상청 인증키 (선택)**
   - Settings → Secrets and variables → Actions → New repository secret → Name `KMA_APIHUB_KEY`.
   - 평년 캐시가 이미 들어 있으므로 매일 전망 산출에는 필요 없습니다. ASOS 평년을 다시 만들 때(`asos.yml`)만 씁니다.
4. **첫 산출**
   - Actions → 「객관기후예측 갱신」 → Run workflow. 몇 분 뒤 `gh-pages` 브랜치가 생깁니다.
5. **웹 게시**
   - Settings → Pages → Build and deployment → Source: **Deploy from a branch** → Branch: **gh-pages / (root)** → Save.
   - 주소: `https://<계정>.github.io/<저장소>/`
6. 이후 매일 07:10 KST(예비 08:40·12:10)에 자동 갱신됩니다.

## 2. 내 PC·서버에서 실행

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r pipeline/requirements.txt
python pipeline/outlook.py            # 실자료 산출 (Open-Meteo 접속 필요), --demo 는 합성 자료
python pipeline/archive.py            # (선택) 발표분 보관
python -m http.server -d site 8000    # http://localhost:8000
```

리눅스 서버에서 매일 돌리려면 crontab 예:
```
10 7 * * *  cd /path/objective_climate_outlook && .venv/bin/python pipeline/outlook.py && rsync -a site/ /var/www/outlook/
```
(시간대가 KST 인 서버 기준. 웹 서버는 `site/` 폴더를 정적 파일로 제공하면 됩니다.)

## 3. 평년 캐시를 새로 만들 때

| 캐시 | 명령 | 필요 | 비고 |
|---|---|---|---|
| `pipeline/cache/era5_daily.npz` | `python pipeline/climatology.py` | Open-Meteo | 호출 한도 시 다시 실행하면 이어받음 |
| `pipeline/cache/asos_daily.npz` | `python pipeline/asos.py` | `KMA_APIHUB_KEY` | 공식 66개 지점 1991–2020 일자료 |
| `pipeline/cache/kma_norm_monthly.json` | `asos.py` 실행 시 함께 생성 | `KMA_APIHUB_KEY` | 기상청 공식 월평년값 (기존 파일을 지우면 다시 받음) |
| `site/data/grid_fine.json` 고도 | `python pipeline/fine_grid.py elev` | Open-Meteo | 격자 자체는 `fine_grid.py build`(shapely 필요) |
| `site/data/grid.json`, `site/data/geo/*` | `python pipeline/build_geo.py <countries-10m.geojson> <countries-50m.geojson>` | shapely, Natural Earth | npm `world-atlas` 를 `topojson-client` 로 GeoJSON 변환해 입력 |

GitHub 에서는 Actions → 「ASOS 관측 평년 구축」 / 「ERA5 평년값 구축」 을 실행하면 같은 일을 하고 결과를 커밋합니다.

## 4. 바꿔 쓰기

- **영역·격자:** `pipeline/config.py` 의 `GRID` 와 `build_geo.py` 의 국가 이름 → `build_geo.py`, `climatology.py` 재실행.
- **요소·임계값:** `config.py` 의 `VARIABLES` (Open-Meteo 일별 변수명, 집계 방식, 임계값).
- **모델:** `config.py` 의 `PRODUCTS` (`ecmwf_ec46`, `ecmwf_seas5`; Open-Meteo Seasonal API 모델명).
- **1개월 주 구성:** `outlook.py` 의 `define_periods` (현재: 월–일, 발표 다음 주의 그다음 주부터 4주).
- **공식 지점·평년 기준:** `config.py` 의 `ASOS_OFFICIAL_66`, `ASOS_MERGE`, `TEMP_TERCILE_SIGMA`, `KOREA_OFFICIAL_MONTHLY`.

## 5. 자료와 이용 조건

- ECMWF EC46·SEAS5·ERA5: Open-Meteo 경유, CC BY 4.0. Open-Meteo 무료 API 는 비상업용이며 호출 한도가 있습니다. 운영 서비스는 상용 키를 권장합니다.
- 기상청 ASOS·평년값: 기상청 API 허브 이용 약관을 따릅니다.
- 경계: Natural Earth(퍼블릭 도메인). 지도 라이브러리: Leaflet(BSD-2, `site/vendor/leaflet`).
