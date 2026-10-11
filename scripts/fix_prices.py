# -*- coding: utf-8 -*-
"""修复 data/prices.csv 中被批量请求截断的个股行情：逐只重取并合并。

背景：westock kline 批量请求（一次多只）时输出表会被截断，导致部分个股
只取到某个区间（如 2025-09-24 之后 / 之前）。单只请求可返回完整区间。
本脚本找出覆盖不足的个股，逐只重拉全区间，按 (code, date) 去重后回写。
"""
import subprocess, sys, os, json, time
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, WESTOCK as EXE  # noqa: E402  路径：本机 Windows 与云端 Linux 通用
OUT = os.path.join(BASE, "data", "prices.csv")
START, END = "2024-01-01", "2026-09-30"


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
    df = pd.read_csv(OUT, dtype={"code": str})
    df = df.drop_duplicates(subset=["code", "date"])
    g = df.groupby("code")["date"].agg(["count", "min", "max"])
    n_full = int(g["count"].max())
    # 覆盖不足 = 条数明显少于众数，或区间起点晚于 2024-01-02（排除真新股由重取结果自然决定）
    bad = g[(g["count"] < n_full * 0.99) | (g["min"] > "2024-01-03")].index.tolist()
    print(f"总数 {len(g)} · 完整 {n_full} 条 · 需修复 {len(bad)}", flush=True)
    print("目标:", " ".join(bad), flush=True)

    sleep_s, fixed, t0 = 6.0, 0, time.time()
    for i, code in enumerate(bad, 1):
        for attempt in range(6):
            try:
                r = subprocess.run([EXE, "kline", code, "--period", "day",
                                    "--start", START, "--end", END, "--fq", "qfq"],
                                   capture_output=True, timeout=180)
                txt = r.stdout.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                txt = ""
            if "服务限频" in txt or not txt.strip():
                sleep_s = min(60.0, sleep_s * 1.6)
                time.sleep(sleep_s)
                continue
            rows = parse(txt)
            add = []
            for r_ in rows:
                d = r_.get("date") or r_.get("Date")
                c = r_.get("last") or r_.get("close") or r_.get("Close")
                if d and c and (r_.get("code") or code):
                    add.append({"code": r_.get("code") or code, "date": d,
                                "close": float(c)})
            if add:
                new = pd.DataFrame(add)
                new = new[new["code"] == code]
                before = len(df[df["code"] == code])
                df = pd.concat([df, new], ignore_index=True)
                df = df.drop_duplicates(subset=["code", "date"], keep="last")
                after = len(df[df["code"] == code])
                fixed += 1
                print(f"[{i}/{len(bad)}] {code} {before}->{after}", flush=True)
            break
        else:
            print(f"[{i}/{len(bad)}] {code} FAILED", flush=True)
        if fixed and fixed % 5 == 0:
            sleep_s = max(3.0, sleep_s * 0.85)
        time.sleep(sleep_s)

    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    df.to_csv(OUT, index=False, encoding="utf-8")
    g2 = df.groupby("code")["date"].agg(["count", "min", "max"])
    print("DONE rows=", len(df), "| 仍不足:", int((g2["count"] < n_full).sum()),
          "| 耗时 %.1f min" % ((time.time() - t0) / 60), flush=True)
    print(g2[g2["count"] < n_full].to_string(), flush=True)


if __name__ == "__main__":
    main()
