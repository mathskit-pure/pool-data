# -*- coding: utf-8 -*-
"""Adaptive bulk fetcher for westock finance data (income/balance/cashflow)."""
import subprocess, sys, os, time, json, re, csv

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, WESTOCK as EXE  # noqa: E402  路径：本机 Windows 与云端 Linux 通用
OUT_DIR = os.path.join(BASE, "data", "raw")
os.makedirs(OUT_DIR, exist_ok=True)

FILES = {"income": os.path.join(OUT_DIR, "income.csv"),
         "balance": os.path.join(OUT_DIR, "balance.csv"),
         "cashflow": os.path.join(OUT_DIR, "cashflow.csv")}
TITLE2KIND = {"利润表": "income", "资产负债表": "balance", "现金流量表": "cashflow"}

PROGRESS_F = os.path.join(OUT_DIR, "progress.json")
STATE_F = os.path.join(OUT_DIR, "state.json")
START, END = "2023-01-01", "2026-06-30"


def load_progress():
    if os.path.exists(PROGRESS_F):
        with open(PROGRESS_F, encoding="utf-8") as f:
            return json.load(f)
    return {"done": [], "failed": {}}


def save_progress(p):
    tmp = PROGRESS_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False)
    os.replace(tmp, PROGRESS_F)


def save_state(st):
    tmp = STATE_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE_F)


def parse_tables(text):
    """Return {kind: (header, rows)} from markdown pipe tables."""
    out = {}
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"\*\*(.+?)\*\*", text)]
    for idx, (pos, title) in enumerate(marks):
        kind = TITLE2KIND.get(title)
        if not kind:
            continue
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(text)
        lines = [ln.strip() for ln in text[pos:end].splitlines() if ln.strip().startswith("|")]
        if len(lines) < 2:
            continue
        header = [c.strip() for c in lines[0].strip("|").split("|")]
        rows = []
        for ln in lines[2:]:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) != len(header):
                continue
            rows.append(dict(zip(header, cells)))
        if rows:
            out[kind] = (header, rows)
    return out


def append_rows(kind, header, rows):
    path = FILES[kind]
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    if exists:
        with open(path, encoding="utf-8") as f:
            old = f.readline().rstrip("\n").split(",")
        if old != header:
            with open(path, encoding="utf-8") as f:
                body = list(csv.reader(f))[1:]
            union = list(old) + [h for h in header if h not in old]
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(union)
                for parts in body:
                    row = dict(zip(old, parts))
                    w.writerow([row.get(h, "") for h in union])
            header = union
    else:
        open(path, "w", encoding="utf-8").write("")  # create
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def run_batch(codes, fields="core"):
    cmd = [EXE, "finance", ",".join(codes), "--start", START, "--end", END]
    if fields != "core":
        cmd += ["--fields", fields]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=240)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    txt = res.stdout.decode("utf-8", errors="replace")
    err = res.stderr.decode("utf-8", errors="replace")
    if "服务限频" in txt or "服务限频" in err:
        return None, "ratelimit"
    if not txt.strip():
        return None, "empty"
    if len(txt) < 400 and "失败" in txt:
        return None, "err:" + txt.strip()[:120]
    return txt, None


def main():
    codes = json.load(open(os.path.join(BASE, "scripts", "codes_todo.json"), encoding="utf-8"))
    prog = load_progress()
    done = set(prog["done"])
    todo = [c for c in codes if c not in done]
    state = json.load(open(STATE_F)) if os.path.exists(STATE_F) else {}
    batch = int(state.get("batch", 8))
    sleep_s = float(state.get("sleep", 6.0))
    fails = 0
    cons_ok = 0
    t0 = time.time()
    print(f"[start] total={len(codes)} todo={len(todo)} batch={batch} sleep={sleep_s}", flush=True)

    i = 0
    while i < len(todo):
        chunk = todo[i:i + batch]
        txt, err = run_batch(chunk)
        if err is not None:
            fails += 1
            cons_ok = 0
            prev_sleep = sleep_s
            sleep_s = min(120.0, sleep_s * 1.5)
            if fails % 3 == 0 and batch > 2:
                batch = max(2, batch - 2)
            save_state({"batch": batch, "sleep": sleep_s})
            print(f"[fail] err={err} batch={batch} sleep {prev_sleep:.1f}->{sleep_s:.1f} done={len(prog['done'])}", flush=True)
            time.sleep(sleep_s)
            if fails > 200:
                print("[abort] persistent failures", flush=True)
                break
            continue

        tables = parse_tables(txt)
        if not tables:
            fails += 1
            print(f"[nofmt] chunk={chunk[:3]}... retry smaller", flush=True)
            if batch > 1:
                batch = max(1, batch // 2)
                save_state({"batch": batch, "sleep": sleep_s})
                continue
            i += len(chunk)
            continue

        for kind, (header, rows) in tables.items():
            append_rows(kind, header, rows)

        got = set()
        for _, (_, rows) in tables.items():
            for r in rows:
                if r.get("code"):
                    got.add(r["code"])
        if not got:
            # cannot attribute rows to codes; treat chunk as done only if all 3 tables present
            got = set(chunk) if len(tables) == 3 else set()

        for c in got:
            prog["failed"].pop(c, None)
            if c not in prog["done"]:
                prog["done"].append(c)
        save_progress(prog)
        print(f"[ok] got={len(got)} done={len(prog['done'])}/{len(codes)} batch={batch} sleep={sleep_s:.1f}", flush=True)

        fails = 0
        cons_ok += 1
        if cons_ok >= 3:
            cons_ok = 0
            prev = sleep_s
            sleep_s = max(3.0, sleep_s * 0.8)
            save_state({"batch": batch, "sleep": sleep_s})
            rate = len(prog["done"]) / max(1e-9, (time.time() - t0) / 60)
            remain = (len(codes) - len(prog["done"])) / max(1e-9, rate)
            print(f"[pace] sleep {prev:.1f}->{sleep_s:.1f} rate={rate:.1f}/min eta={remain:.0f}min", flush=True)
        i += len(chunk)
        time.sleep(sleep_s)

    print(f"[done] fetched={len(prog['done'])} failed={len(prog['failed'])}", flush=True)


if __name__ == "__main__":
    main()
