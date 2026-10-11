# -*- coding: utf-8 -*-
"""拉取对比基准指数日线：沪深300 / 创业板50 / 科创50。"""
import subprocess
import sys
import os
from datetime import date
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE, WESTOCK as EXE  # noqa: E402  路径：本机 Windows 与云端 Linux 通用
OUT = os.path.join(BASE, "data", "bench_all.csv")

BENCH = {"沪深300": "sh000300", "创业板50": "sz399673", "科创50": "sh000688"}
START = "2024-01-01"


def main():
    end = date.today().strftime("%Y-%m-%d")
    series = {}
    for name, code in BENCH.items():
        r = subprocess.run([EXE, "kline", code, "--period", "day",
                            "--start", START, "--end", end, "--fq", "qfq"],
                           capture_output=True, timeout=300)
        txt = r.stdout.decode("utf-8", errors="replace")
        dates, vals = [], []
        for ln in txt.splitlines():
            ln = ln.strip()
            if not ln.startswith("|"):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) < 3 or cells[0] in ("date", "code"):
                continue
            if set(cells[0]) <= set("- :"):
                continue
            try:
                # 单指数返回列为 date, open, last, ...
                d = cells[0] if cells[0][:2].isdigit() else cells[1]
                v = float(cells[2] if cells[0][:2].isdigit() else cells[3])
            except (ValueError, IndexError):
                continue
            dates.append(d)
            vals.append(v)
        s = pd.Series(vals, index=pd.to_datetime(pd.Series(dates)), name=name)
        s = s[~s.index.duplicated()].sort_index()
        series[name] = s
        print(f"{name} {code}: {len(s)} 行 {s.index.min().date()} → {s.index.max().date()}", flush=True)
    df = pd.DataFrame(series)
    df.to_csv(OUT, encoding="utf-8-sig")
    print("written:", OUT, df.shape, flush=True)


if __name__ == "__main__":
    main()
