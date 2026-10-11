# -*- coding: utf-8 -*-
"""
更新「最新一季股池」——在 A 股定期报告全部披露完成的次月首日运行。

用法：
    python scripts/update_latest.py                 # 按当天日期自动推断最新报告期
    python scripts/update_latest.py --period 2026-09-30
    python scripts/update_latest.py --no-fetch      # 不重新拉财报，仅重算并刷新页面
    python scripts/update_latest.py --no-import     # 不上传页面（仅本地重算）

流程：
    1) 确定目标报告期（一季报 03-31 / 中报 06-30 / 三季报 09-30）
    2) 拉取固定标的清单（codes_big.json，市值≥300亿的 566 只，不随市值与指数调整变化）
       在该报告期及前推一年的三大报表，追加进 data/raw 并按 code|EndDate 去重（保留最新）
    3) score2.py  舞弊调整质量因子评分（自动纳入新的报告期）
    4) pool.py    申万三级行业各取前 5，重建全量季度股池
    5) fetch_prices.py  重拉股池个股前复权日线
    5b) fix_prices.py   校验行情完整性（批量请求会截断部分个股），逐只补拉
    6) fetch_bench.py   沪深300 / 创业板50 / 科创50 基准
    7) backtest.py      动量轮动 + 质量Top20 等权回测（N=10 / K=5 / L=12 / 单行业≤2）
    8) gen_page.py      重新生成页面
    9) import_html.py   以 --node-block-id 覆写资料库中已有的页面节点
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = r"C:\Users\12066\WorkBuddy\2026-10-04-19-37-33"
PY = r"C:\Users\12066\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
EXE = r"C:\Users\12066\.local\bin\westock.exe"
SKILL = (r"C:\Users\12066\.workbuddy\plugins\cache\workbuddy-builtin\skill-library"
         r"\5.7.3-wb.40038958.gaa9f13d9.hff9adc917099")
RAW = os.path.join(BASE, "data", "raw")
PAGE_NODE = "iB8I58mCTooLicPQ0Kyq0M"          # 资料库页面节点（覆写目标）
SPACE_ID = "EZaiULPjRP7ghX3LGRl1HO"

# 定期报告披露截止次月首日：5/1 更新一季报、9/1 更新中报、11/1 更新三季报
ASOF_MONTH = {"03-31": 5, "06-30": 9, "09-30": 11}


def infer_period(today=None):
    """按当天日期推断「已全部披露完成」的最新报告期。"""
    t = today or time.localtime()
    y, m = t.tm_year, t.tm_mon
    if m >= 11:
        return f"{y}-09-30"
    if m >= 9:
        return f"{y}-06-30"
    if m >= 5:
        return f"{y}-03-31"
    return f"{y - 1}-09-30"


def asof_of(end):
    return f"{end[:4]}-{ASOF_MONTH[end[5:10]]:02d}-01"


def dedup_raw():
    """按 code|EndDate 去重，保留最后一次抓到的记录（最新值优先）。"""
    for name in ("income", "balance", "cashflow"):
        path = os.path.join(RAW, f"{name}.csv")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            continue
        hdr, body = rows[0], rows[1:]
        try:
            ic, id_ = hdr.index("code"), hdr.index("EndDate")
        except ValueError:
            continue
        seen, keep = {}, []
        for r in body:
            if len(r) <= max(ic, id_):
                continue
            k = (r[ic], r[id_])
            if k in seen:
                keep[seen[k]] = r          # 后出现的覆盖先出现的
            else:
                seen[k] = len(keep)
                keep.append(r)
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(hdr)
            w.writerows(keep)
        print(f"[dedup] {name}: {len(body)} -> {len(keep)}", flush=True)


def fetch_fin(period):
    """拉取固定清单在 [上一年初, period] 区间的三大报表（带自适应限频退避）。"""
    sys.path.insert(0, os.path.join(BASE, "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fetchmod", os.path.join(BASE, "scripts", "fetch.py"))
    fm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fm)

    codes = json.load(open(os.path.join(BASE, "scripts", "codes_big.json"), encoding="utf-8"))
    start = f"{int(period[:4]) - 1}-01-01"
    fm.START, fm.END = start, period
    prog_f = os.path.join(RAW, f"progress_{period}.json")
    fm.PROGRESS_F = prog_f

    prog = json.load(open(prog_f, encoding="utf-8")) if os.path.exists(prog_f) else {"done": [], "failed": {}}
    done = set(prog["done"])
    todo = [c for c in codes if c not in done]
    state_f = os.path.join(RAW, "state.json")
    state = json.load(open(state_f)) if os.path.exists(state_f) else {}
    batch, sleep_s = int(state.get("batch", 6)), float(state.get("sleep", 8.0))
    print(f"[fetch] period={period} window={start}..{period} todo={len(todo)}", flush=True)

    i, fails, cons_ok, t0 = 0, 0, 0, time.time()
    while i < len(todo):
        chunk = todo[i:i + batch]
        txt, err = fm.run_batch(chunk)
        if err is not None:
            fails += 1
            cons_ok = 0
            sleep_s = min(120.0, sleep_s * 1.5)
            if fails % 3 == 0 and batch > 2:
                batch = max(2, batch - 2)
            print(f"[fail] {err} batch={batch} sleep={sleep_s:.1f} done={len(done)}", flush=True)
            time.sleep(sleep_s)
            if fails > 300:
                print("[abort] 连续失败过多", flush=True)
                break
            continue
        tables = fm.parse_tables(txt)
        if not tables:
            fails += 1
            if batch > 1:
                batch = max(1, batch // 2)
                continue
            i += len(chunk)
            continue
        for kind, (header, rows) in tables.items():
            fm.append_rows(kind, header, rows)
        got = {r.get("code") for _, (_, rows) in tables.items() for r in rows if r.get("code")}
        for c in got:
            done.add(c)
        prog["done"] = sorted(done)
        json.dump(prog, open(prog_f, "w", encoding="utf-8"), ensure_ascii=False)
        fails = 0
        cons_ok += 1
        if cons_ok >= 3:
            cons_ok = 0
            sleep_s = max(3.0, sleep_s * 0.8)
        rate = len(done) / max(1e-9, (time.time() - t0) / 60)
        print(f"[ok] done={len(done)}/{len(codes)} rate={rate:.1f}/min "
              f"eta={(len(codes) - len(done)) / max(1e-9, rate):.0f}min", flush=True)
        i += len(chunk)
        time.sleep(sleep_s)
    fm.save_state({"batch": batch, "sleep": sleep_s})
    print(f"[fetch] 完成 {len(done)}/{len(codes)}", flush=True)


def run(script, *args):
    cmd = [PY, os.path.join(BASE, "scripts", script), *args]
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()[-8:]
    print("\n".join(tail), flush=True)
    if r.returncode != 0:
        print((r.stderr or "").strip()[-1500:], flush=True)
        raise SystemExit(f"{script} 失败 (exit={r.returncode})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default=None, help="目标报告期，如 2026-09-30")
    ap.add_argument("--no-fetch", action="store_true", help="跳过财报抓取")
    ap.add_argument("--no-import", action="store_true", help="跳过页面上传")
    a = ap.parse_args()

    period = a.period or infer_period()
    print(f"[period] 目标报告期 = {period}（信息可得日 {asof_of(period)}）", flush=True)

    if not a.no_fetch:
        fetch_fin(period)
        dedup_raw()
    else:
        print("[fetch] 已跳过", flush=True)

    # 价格需要覆盖到最新交易日：清掉旧价格后重拉（脚本本身支持断点续传）
    for f in ("prices.csv", "price_progress.json"):
        p = os.path.join(BASE, "data", f)
        if os.path.exists(p):
            os.remove(p)

    run("score2.py")
    run("pool.py")
    run("fetch_prices.py")
    run("fix_prices.py")    # 批量请求会截断部分个股行情，逐只校验补拉
    run("fetch_bench.py")   # 沪深300 / 创业板50 / 科创50
    run("backtest.py")
    run("gen_page.py")

    if not a.no_import:
        cmd = [PY, os.path.join(SKILL, "page", "import_html.py"),
               os.path.join(BASE, "data", "pool_page.html"),
               "--file-name", "舞弊调整质量因子·季度动态股池.html",
               "--node-block-id", PAGE_NODE,
               "--space-id", SPACE_ID]
        print(f"\n>>> {' '.join(cmd[:3])} ...", flush=True)
        env = dict(os.environ, CODEBUDDY_SKILL_DIR=SKILL)
        r = subprocess.run(cmd, cwd=SKILL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        out = (r.stdout or "") + (r.stderr or "")
        for ln in out.strip().splitlines():
            if ln.strip().startswith("KS_IMPORT_OK"):
                print("[import]", ln.strip(), flush=True)
            elif r.returncode != 0:
                print(ln.strip()[:300], flush=True)

    print(f"\n[done] 已更新至 {period} 股池", flush=True)


if __name__ == "__main__":
    main()
