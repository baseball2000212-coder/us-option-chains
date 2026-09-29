# 미국 옵션 체인 자동 수집

SPY·TSLA·AAPL·NVDA·IBIT **전 만기·전 행사가 옵션 체인**을 하루 10번, 정해진 시각에 자동으로 모읍니다.
1시간 간격 델타헤지 손익 백테스트에 쓰려는 데이터입니다. 델타헤지한 옵션 포지션의 손익은 대략

$$ \tfrac12\,\Gamma\,(\Delta S)^2 + \Theta\,\Delta t $$

로 감마와 세타가 결정하는데, 이를 실제 체인 데이터로 확인하려는 것입니다.

![예시](figures/example.png)

## 무엇을 모으나

| 항목 | 내용 |
|---|---|
| 종목 | SPY, TSLA, AAPL, NVDA, IBIT |
| 범위 | 전 만기, 전 행사가 (SPY는 1회 약 13,000행) |
| 시각 (뉴욕) | 09:45 ~ 15:45 매시, 16:15, 16:45, 장 마감 후 — 하루 10회 |
| 필드 | 매수·매도 호가와 잔량, 내재변동성, 델타·감마·베가·세타·로, 거래량, 미결제약정, 기초자산 가격, 수집 시각 |
| 출처 | CBOE 공개 지연 시세 |
| 기간 | 2026-08-28부터 |

## 어떻게 돌아가나

```
cron-job.org (정시)  ──▶  GitHub Actions (이 저장소)  ──▶  CBOE 지연 시세
                                   │
                                   └──▶  비공개 데이터 저장소에 커밋 (회차당 1개, gzip CSV)
```

- **정시 수집**: GitHub Actions 예약 실행은 수십 분씩 늦을 수 있어서, 외부 크론이 정시 전에 작업을 깨우고 스크립트가 목표 시각까지 기다렸다가 받습니다. 목표 시각은 뉴욕 시간으로 계산해 서머타임이 자동 처리됩니다.
- **백업**: GitHub 자체 예약도 걸어 두고, 같은 시간대 작업이 겹치면 하나는 대기시킵니다. 이미 지난 회차는 건너뛰어 중복 수집이 없습니다.
- **코드와 데이터 분리**: 이 저장소에는 코드만 있고, 데이터는 비공개 저장소에 GitHub API로 저장합니다. 접근 토큰은 데이터 저장소 쓰기 권한만 가진 것을 Actions Secret으로 넣습니다.
- **용량**: 회차별 파일을 gzip으로 압축해(약 1/5) 저장소가 너무 커지지 않게 합니다.

## 쓰는 법

```bash
pip install -r requirements.txt
python collect_cboe.py eod      # 지금 1회 수집 → data/ (DATA_TOKEN 없으면 로컬 저장)
```

```python
import pandas as pd
df = pd.read_csv("data/SPY/2026-09-28/SPY_2026-09-28_1045.csv.gz", parse_dates=["expiry"])
```

Actions에서 돌릴 때 필요한 설정: Secret `DATA_TOKEN`(데이터 저장소 Contents 쓰기 권한), Variable `DATA_REPO`(예: `owner/data`).
