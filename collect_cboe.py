"""
CBOE 지연 옵션 체인 수집기 — 정해진 시각(ET)에 5종목 전체 체인을 받아 저장.
  python collect_cboe.py am    → 9:45, 10:45, 11:45, 12:45 ET
  python collect_cboe.py pm    → 13:45, 14:45, 15:45, 16:15, 16:45 ET
  python collect_cboe.py eod   → 즉시 1회 (장 마감 후)
잡을 일찍 띄우고 목표 시각까지 기다렸다가 받는다 (GitHub Actions 예약 실행은 수십 분 늦을 수 있어서).
목표 시각은 ET로 계산하므로 서머타임은 자동 처리된다.

저장 위치
  - 환경변수 DATA_TOKEN이 있으면: 비공개 데이터 저장소(DATA_REPO)에 GitHub API로 커밋 (회차당 커밋 1개)
  - 없으면: 로컬 data/ 폴더 (테스트용)
파일: data/{종목}/{날짜}/{종목}_{날짜}_{회차}.csv.gz  (gzip CSV, pandas.read_csv로 바로 읽힘)
"""
import base64, io, os, re, sys, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests

TICKERS = ["SPY", "TSLA", "AAPL", "NVDA", "IBIT"]   # 지수는 "_SPX"처럼 앞에 _
ET = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAT = re.compile(r"^(\D+)(\d{6})([CP])(\d{8})$")
SCHEDULE = {
    "am": [(9, 45), (10, 45), (11, 45), (12, 45)],
    "pm": [(13, 45), (14, 45), (15, 45), (16, 15), (16, 45)],   # 16:15 = 주식 종가(16:00) 반영, 16:45 = 옵션 마감(16:15) 이후
}
DATA_TOKEN = os.environ.get("DATA_TOKEN", "")
DATA_REPO = os.environ.get("DATA_REPO", "")          # 예: owner/data (비공개)
DATA_BRANCH = os.environ.get("DATA_BRANCH", "main")


def fetch(sym):
    """CBOE 지연 시세 JSON → 옵션별 한 줄 DataFrame (만기·콜풋·행사가 분리, 기초자산 가격·수집 시각 추가)."""
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    js = r.json()
    d = js["data"]
    df = pd.DataFrame(d["options"])
    if df.empty:
        return df
    m = df["option"].str.extract(PAT)
    df.insert(1, "root", m[0])
    df.insert(2, "expiry", pd.to_datetime("20" + m[1], format="%Y%m%d").dt.date)
    df.insert(3, "cp", m[2])
    df.insert(4, "strike", m[3].astype(int) / 1000)
    df.insert(0, "underlying", sym.lstrip("_"))
    df["spot"] = d.get("current_price")
    df["cboe_timestamp"] = js.get("timestamp")
    df["collected_et"] = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")
    return df.sort_values(["expiry", "cp", "strike"]).reset_index(drop=True)


# ---------- 저장 ----------
def _gh(method, path, **kw):
    r = requests.request(method, f"https://api.github.com/repos/{DATA_REPO}/{path}", timeout=60,
                         headers={"Authorization": f"Bearer {DATA_TOKEN}", "Accept": "application/vnd.github+json"}, **kw)
    return r


def push_files(files, message):
    """files = {경로: bytes} → 비공개 저장소에 커밋 1개로 추가. 동시에 다른 커밋이 들어오면 다시 시도."""
    blobs = []
    for path, data in files.items():
        r = _gh("POST", "git/blobs", json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        r.raise_for_status()
        blobs.append({"path": path, "mode": "100644", "type": "blob", "sha": r.json()["sha"]})
    for attempt in range(6):
        head = _gh("GET", f"git/ref/heads/{DATA_BRANCH}"); head.raise_for_status()
        parent = head.json()["object"]["sha"]
        base_tree = _gh("GET", f"git/commits/{parent}").json()["tree"]["sha"]
        tree = _gh("POST", "git/trees", json={"base_tree": base_tree, "tree": blobs}); tree.raise_for_status()
        commit = _gh("POST", "git/commits", json={"message": message, "tree": tree.json()["sha"], "parents": [parent]}); commit.raise_for_status()
        upd = _gh("PATCH", f"git/refs/heads/{DATA_BRANCH}", json={"sha": commit.json()["sha"]})
        if upd.ok:
            return
        time.sleep(3 * (attempt + 1))
    upd.raise_for_status()


def save(files, message):
    if DATA_TOKEN and DATA_REPO:
        push_files(files, message)
        print(f"[saved] {len(files)} files → {DATA_REPO}", flush=True)
    else:
        for path, data in files.items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        print(f"[saved] {len(files)} files → local", flush=True)


def collect(tag):
    """5종목 한 번 수집 후 저장. 실패한 종목 수를 반환."""
    day = datetime.now(ET).strftime("%Y-%m-%d")
    files, fails = {}, 0
    for sym in TICKERS:
        try:
            df = fetch(sym)
            name = sym.lstrip("_")
            buf = io.BytesIO(); df.to_csv(buf, index=False, compression={"method": "gzip", "mtime": 0})
            files[f"data/{name}/{day}/{name}_{day}_{tag}.csv.gz"] = buf.getvalue()
            print(f"[ok] {datetime.now(ET):%H:%M:%S} ET  {name} {tag}: {len(df):>6} rows", flush=True)
        except Exception as e:
            fails += 1
            print(f"[FAIL] {sym} {tag}: {e}", file=sys.stderr, flush=True)
        time.sleep(1)
    if files:
        for attempt in range(3):                                 # 공개 저장소라 아티팩트 백업은 안 씀 (누구나 받을 수 있음) → 재시도만
            try:
                save(files, f"collect {tag} {day}"); break
            except Exception as e:
                print(f"[FAIL] save (시도 {attempt + 1}/3): {e}", file=sys.stderr, flush=True)
                time.sleep(20 * (attempt + 1))
        else:
            fails += len(files)
    return fails


def sleep_until(target):
    while (remaining := (target - datetime.now(ET)).total_seconds()) > 0:
        time.sleep(min(remaining, 60))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "eod"
    now = datetime.now(ET)
    if now.weekday() >= 5:
        print("skip: 주말")
        return
    if mode == "eod":
        sys.exit(1 if collect("eod") else 0)
    total_fails = 0
    for h, mnt in SCHEDULE[mode]:
        target = now.replace(hour=h, minute=mnt, second=0, microsecond=0)
        if datetime.now(ET) > target + timedelta(minutes=20):
            print(f"skip {h:02d}{mnt:02d}: 잡이 너무 늦게 시작됨", flush=True)
            continue
        print(f"waiting for {target:%H:%M} ET ...", flush=True)
        sleep_until(target)
        total_fails += collect(f"{h:02d}{mnt:02d}")
    sys.exit(1 if total_fails else 0)


if __name__ == "__main__":
    main()
