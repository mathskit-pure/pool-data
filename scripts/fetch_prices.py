# -*- coding: utf-8 -*-
"""拉取股池个股的前复权日线（回测用）。"""
import subprocess, sys, os, json, time, csv
from datetime import date

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, WESTOCK as EXE  # noqa: E402  路径：本机 Windows 与云端 Linux 通用
OUT = os.path.join(BASE, "data", "prices.csv")
PROG = os.path.join(BASE, "data", "price_progress.json")
START = "2024-01-01"
END = date.today().strftime("%Y-%m-%d")     # 每次更新自动拉到最新交易日


def parse(txt):
    rows, hdr = [], None
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if hdr is None:
            hdr = cells
            continue
        if set("".join(cells)) <= set("- :"):
            continue
        if len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    return rows


def main():
    codes = json.load(open(os.path.join(BASE, "scripts", "codes_pool.json"), encoding="utf-8"))
    prog = json.load(open(PROG, encoding="utf-8")) if os.path.exists(PROG) else {"done": []}
    done = set(prog["done"])
    todo = [c for c in codes if c not in done]
    print(f"total={len(codes)} todo={len(todo)}", flush=True)

    exists = os.path.exists(OUT) and os.path.getsize(OUT) > 0
    f = open(OUT, "a", encoding="utf-8", newline="")
    w = None
    # 批量请求过大时返回表会被截断，故批次取小；剩余缺口由 fix_prices.py 逐只补齐
    batch, sleep_s = 4, 6.0
    i = 0
    cons_ok = 0
    t0 = time.time()
    while i < len(todo):
        chunk = todo[i:i + batch]
        try:
            r = subprocess.run([EXE, "kline", ",".join(chunk), "--period", "day",
                                "--start", START, "--end", END, "--fq", "qfq"],
                               capture_output=True, timeout=300)
            txt = r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            txt = ""
        if "服务限频" in txt or not txt.strip():
            sleep_s = min(120.0, sleep_s * 1.5)
            cons_ok = 0
            if batch > 2:
                batch = max(2, batch - 2)
            print(f"[fail] batch={batch} sleep={sleep_s:.1f} done={len(done)}", flush=True)
            time.sleep(sleep_s)
            continue
        rows = parse(txt)
        if not rows:
            i += len(chunk)
            continue
        if w is None:
            w = csv.DictWriter(f, fieldnames=["code", "date", "close"], extrasaction="ignore")
            if not exists:
                w.writeheader()
        n = 0
        for r in rows:
            d = r.get("date") or r.get("Date")
            c = r.get("last") or r.get("close") or r.get("Close")
            if not d or not c:
                continue
            w.writerow({"code": r.get("code"), "date": d, "close": c})
            n += 1
        got = {r.get("code") for r in rows if r.get("code")}
        for c in (got or set(chunk)):
            done.add(c)
        prog["done"] = sorted(done)
        json.dump(prog, open(PROG, "w", encoding="utf-8"), ensure_ascii=False)
        f.flush()
        cons_ok += 1
        if cons_ok >= 3:
            cons_ok = 0
            sleep_s = max(3.0, sleep_s * 0.8)
        rate = len(done) / max(1e-9, (time.time() - t0) / 60)
        print(f"[ok] rows={n} done={len(done)}/{len(codes)} rate={rate:.1f}/min", flush=True)
        i += len(chunk)
        time.sleep(sleep_s)
    f.close()
    print("DONE", len(done), flush=True)


if __name__ == "__main__":
    main()
