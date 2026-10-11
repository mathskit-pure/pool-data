# -*- coding: utf-8 -*-
"""
龙头动量轮动策略（标的池 = 舞弊调整质量因子季度动态股池）
==========================================================
模型来源：《龙头动量轮动策略代码更新》
  · 风险调整动量  Adj_Momentum = N日平均收益率 / sqrt(N日收益率方差)
  · 双重选股：原始动量为正 → 按 Adj_Momentum 取前 L 只
  · 权重：Adj_Momentum 归一化（w_i = adj_i / Σadj）
  · 权重滞后 1 日（T 日决策、T+1 日执行），规避未来函数
  · 调仓：每 K 个交易日，权重生效至下一次调仓日前一日，无缝衔接

本实现在原文基础上：
  1) 固定标的池 → 按季更新的「舞弊调整质量因子」股池
  2) 新增约束：单个申万三级行业最多 2 只；出现第 3 只时剔除动量最低者并按序补录
"""
import sys, os, json
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE  # noqa: E402  路径：本机 Windows 与云端 Linux 通用

N = 10      # 动量测算周期
K = 5       # 调仓间隔（交易日）
L = 12      # 动量组合持仓数量
MAX_PER_IND = 2
LQ = 20     # 质量 Top 组合持仓数量
MAX_PER_IND_Q = 2
START = "2024-05-06"


def load():
    px = pd.read_csv(os.path.join(BASE, "data", "prices.csv"), dtype={"code": str})
    px["date"] = pd.to_datetime(px["date"])
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px = px.dropna(subset=["close"]).drop_duplicates(["code", "date"])
    close = px.pivot(index="date", columns="code", values="close").sort_index()
    meta = json.load(open(os.path.join(BASE, "scripts", "meta.json"), encoding="utf-8"))
    pools = json.load(open(os.path.join(BASE, "data", "pools.json"), encoding="utf-8"))
    sw3 = {c: (meta.get(c, {}).get("sw3") or "未分类") for c in close.columns}
    name = {c: (meta.get(c, {}).get("name") or c) for c in close.columns}

    # 报告期 → 可得日
    asof = sorted([(v["asof"], k) for k, v in pools.items() if v.get("asof")])
    pool_by_period = {k: [m["code"] for m in v["members"]] for k, v in pools.items()}
    # 报告期 → 股池内个股的舞弊调整质量因子得分（供质量 Top 组合选股）
    score_by_period = {k: sorted(((m["code"], float(m["FAQ_score"]))
                                  for m in v["members"] if m.get("FAQ_score") is not None),
                                 key=lambda x: -x[1])
                       for k, v in pools.items()}
    return close, sw3, name, asof, pool_by_period, score_by_period


def active_period(d, asof):
    cur = None
    for a, period in asof:
        if pd.Timestamp(a) <= d:
            cur = period
    return cur


def active_pool(d, asof, pool_by_period):
    cur = active_period(d, asof)
    return pool_by_period.get(cur, []) if cur else []


def select(mom_row, adj_row, candidates, sw3):
    """正动量 → 按 Adj_Momentum 排序 → 单行业最多 2 只 → 取前 L 只"""
    cand = [(c, mom_row[c], adj_row[c]) for c in candidates
            if c in mom_row.index and pd.notna(mom_row[c]) and pd.notna(adj_row[c])
            and mom_row[c] > 0]
    cand.sort(key=lambda x: -x[2])
    picked, ind_cnt = [], {}
    for c, m, a in cand:
        if len(picked) >= L:
            break
        ind = sw3.get(c, "未分类")
        if ind_cnt.get(ind, 0) >= MAX_PER_IND:
            continue                      # 第 3 只同行业 → 剔除（动量最低者）
        ind_cnt[ind] = ind_cnt.get(ind, 0) + 1
        picked.append((c, a))
    return picked


def select_by_score(d, asof, score_by_period, sw3, close):
    """质量 Top 组合：当期股池内按 FAQ 得分降序 → 单行业最多 2 只 → 取前 LQ 只，等权。
    同行业出现第 3 只时跳过（即剔除其中得分最低者）并继续按序补录。"""
    period = active_period(d, asof)
    if not period:
        return []
    cand = [(c, s) for c, s in score_by_period.get(period, []) if c in close.columns]
    picked, ind_cnt = [], {}
    for c, s in cand:                       # 已按得分降序排好
        if len(picked) >= LQ:
            break
        ind = sw3.get(c, "未分类")
        if ind_cnt.get(ind, 0) >= MAX_PER_IND_Q:
            continue                        # 第 3 只同行业 → 剔除（得分最低者）
        ind_cnt[ind] = ind_cnt.get(ind, 0) + 1
        picked.append(c)
    return picked


def perf(ret, label):
    ret = ret.dropna()
    if len(ret) == 0:
        return {}
    eq = (1 + ret).cumprod()
    n = len(ret)
    ann = eq.iloc[-1] ** (252 / n) - 1
    vol = ret.std(ddof=0) * np.sqrt(252)
    mdd = (eq / eq.cummax() - 1).min()
    sharpe = ann / vol if vol else np.nan
    calmar = ann / abs(mdd) if mdd else np.nan
    return {"组合": label, "累计收益": eq.iloc[-1] - 1, "年化收益": ann, "年化波动": vol,
            "最大回撤": mdd, "夏普比率": sharpe, "卡玛比率": calmar, "交易日数": n}


def main():
    close, sw3, name, asof, pool_by_period, score_by_period = load()
    print("价格矩阵:", close.shape, close.index.min(), "→", close.index.max(), flush=True)

    ret = close.pct_change()
    mom = ret.rolling(N).mean()          # N 日平均收益率（原始动量）
    vol = ret.rolling(N).var()           # N 日收益率方差
    adj = mom / np.sqrt(vol)             # 风险调整动量

    dates = close.index
    # 调仓日：自 START 起，每 K 个交易日
    start_pos = int(np.searchsorted(dates.values, np.datetime64(START)))
    reb_pos = list(range(start_pos, len(dates), K))
    print(f"回测起点 {dates[start_pos].date()} | 调仓次数 {len(reb_pos)}", flush=True)

    def price_at(code, d):
        """取 d 日（或之前最近交易日）收盘价，用于计算持仓区间涨跌幅。"""
        s = close[code]
        v = s.get(d, np.nan) if d in s.index else np.nan
        if pd.notna(v):
            return float(v)
        ss = s.loc[:d].dropna()
        return float(ss.iloc[-1]) if len(ss) else np.nan

    W = pd.DataFrame(0.0, index=dates, columns=close.columns)
    Wq = pd.DataFrame(0.0, index=dates, columns=close.columns)   # 质量 Top20 等权
    holdings_rows = []
    removed_rows = []
    qual_rows = []
    qual_removed = []
    prev_set, entry_of = set(), {}          # 上一期持仓 / 个股本轮建仓日
    last_q_period, prev_qw = None, pd.Series(0.0, index=close.columns)
    q_prev_set, q_entry_of = set(), {}      # 质量组合：上季持仓 / 个股本轮建仓日
    for j, pos in enumerate(reb_pos):
        end_pos = reb_pos[j + 1] - 1 if j + 1 < len(reb_pos) else len(dates) - 1
        d = dates[pos]

        pool = [c for c in active_pool(d, asof, pool_by_period) if c in close.columns]
        picked = select(mom.iloc[pos], adj.iloc[pos], pool, sw3)
        if picked:
            tot = sum(a for _, a in picked)
            if tot > 0:
                for c, a in picked:
                    W.iloc[pos:end_pos + 1, W.columns.get_loc(c)] = a / tot
            else:
                for c, a in picked:
                    W.iloc[pos:end_pos + 1, W.columns.get_loc(c)] = 1.0 / len(picked)
        cur_set = {c for c, _ in picked}
        tot = sum(a for _, a in picked)

        # 本期被剔除：上一期持有、本期不再持有 → 记录建仓日至剔除日的区间涨跌幅
        for c in sorted(prev_set - cur_set):
            e = entry_of.pop(c, None)
            p0 = price_at(c, e) if e is not None else np.nan
            p1 = price_at(c, d)
            chg = (p1 / p0 - 1) if (p0 and p1 and np.isfinite(p0) and np.isfinite(p1)) else np.nan
            removed_rows.append({"调仓日": d.date(), "代码": c, "名称": name.get(c, c),
                                 "申万三级": sw3.get(c, "未分类"),
                                 "建仓日": e.date() if e is not None else None,
                                 "剔除日": d.date(), "区间涨跌幅": chg})

        for rank, (c, a) in enumerate(picked, 1):
            if c not in prev_set:
                entry_of[c] = d            # 新纳入 → 记录建仓日
            holdings_rows.append({
                "调仓日": d.date(), "次序": rank, "代码": c,
                "名称": name.get(c, c), "申万三级": sw3.get(c, "未分类"),
                "原始动量": mom.iloc[pos][c], "调整动量": a,
                "权重": (a / tot) if tot else 0,
                "状态": "新增" if c not in prev_set else "持有"})
        prev_set = cur_set

    # ── 质量 Top 组合：季度买入持有 ──────────────────────────────────────
    # 仅在季度股池更新（信息可得日后的首个交易日）换仓并等权建仓；
    # 同一季度内不再平衡，权重随价格自然漂移（买入持有）。
    for pos in range(start_pos, len(dates)):
        d = dates[pos]
        per = active_period(d, asof)
        if per != last_q_period:                       # 新季度 → 换仓、等权重新建仓
            last_q_period = per
            qcodes = select_by_score(d, asof, score_by_period, sw3, close)
            w = pd.Series(0.0, index=close.columns)
            if qcodes:
                w[qcodes] = 1.0 / len(qcodes)
            qset = set(qcodes)

            # 本季被剔除：上季持有、本季不再持有 → 建仓日至剔除日累计涨跌幅
            for c in sorted(q_prev_set - qset):
                e = q_entry_of.pop(c, None)
                p0 = price_at(c, e) if e is not None else np.nan
                p1 = price_at(c, d)
                chg = (p1 / p0 - 1) if (p0 and p1 and np.isfinite(p0) and np.isfinite(p1)) else np.nan
                qual_removed.append({"调仓日": d.date(), "代码": c, "名称": name.get(c, c),
                                     "申万三级": sw3.get(c, "未分类"),
                                     "建仓日": e.date() if e is not None else None,
                                     "区间涨跌幅": chg})

            smap = dict(score_by_period.get(per, []))
            for rank, c in enumerate(qcodes, 1):
                if c not in q_prev_set:
                    q_entry_of[c] = d
                qual_rows.append({"报告期": per, "调仓日": d.date(), "次序": rank,
                                  "代码": c, "名称": name.get(c, c),
                                  "申万三级": sw3.get(c, "未分类"),
                                  "FAQ得分": smap.get(c), "建仓权重": 1.0 / len(qcodes),
                                  "状态": "新增" if c not in q_prev_set else "持有"})
            q_prev_set = qset
        else:                                          # 季度内不动，权重自然漂移
            r = ret.iloc[pos].reindex(close.columns).fillna(0.0)
            w = prev_qw * (1.0 + r)
            s = float(w.sum())
            w = (w / s) if s else prev_qw
        Wq.iloc[pos] = w.values
        prev_qw = w

    # 等权重对照（同一动态股池）
    We = pd.DataFrame(0.0, index=dates, columns=close.columns)
    for j, pos in enumerate(reb_pos):
        end_pos = reb_pos[j + 1] - 1 if j + 1 < len(reb_pos) else len(dates) - 1
        d = dates[pos]
        pool = [c for c in active_pool(d, asof, pool_by_period) if c in close.columns]
        if pool:
            We.iloc[pos:end_pos + 1, [We.columns.get_loc(c) for c in pool]] = 1.0 / len(pool)

    mask = dates >= pd.Timestamp(START)
    # 权重滞后 1 日：T 日决策、T+1 日执行
    strat = (W.shift(1) * ret).sum(axis=1)[mask]
    equal = (We.shift(1) * ret).sum(axis=1)[mask]
    qual = (Wq.shift(1) * ret).sum(axis=1)[mask]

    rows = [perf(strat, "动量轮动策略"), perf(equal, "动量轮动策略（等权）"), perf(qual, "质量Top20等权")]
    bench_eq = None
    bm_all = os.path.join(BASE, "data", "bench_all.csv")
    bench_map = {}
    if os.path.exists(bm_all):
        b = pd.read_csv(bm_all, index_col=0)
        b.index = pd.to_datetime(b.index)
        for c in ["沪深300", "创业板50", "科创50"]:
            if c in b.columns:
                bench_map[c] = b[c].sort_index()
    elif os.path.exists(os.path.join(BASE, "data", "bench.csv")):
        b = pd.read_csv(os.path.join(BASE, "data", "bench.csv"))
        b["date"] = pd.to_datetime(b["date"])
        bench_map["沪深300"] = b.set_index("date")["close"].sort_index()

    for name, s in bench_map.items():
        br = s.pct_change().reindex(strat.index)
        # 与策略对齐：策略首日无权重（T 决策 T+1 执行），基准首日收益同样不计入
        if len(br):
            br.iloc[0] = 0.0
        rows.append(perf(br.fillna(0.0), name))
        col = (1 + br.fillna(0.0)).cumprod()
        bench_eq = col.to_frame(name) if bench_eq is None else bench_eq.join(col)

    summary = pd.DataFrame(rows)
    print("\n=== 绩效汇总 ===", flush=True)
    print(summary.to_string(index=False), flush=True)

    out_dir = os.path.join(BASE, "data")
    summary.to_csv(os.path.join(out_dir, "backtest_summary.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(holdings_rows).to_csv(os.path.join(out_dir, "holdings.csv"),
                                       index=False, encoding="utf-8-sig")
    pd.DataFrame(removed_rows).to_csv(os.path.join(out_dir, "removed.csv"),
                                      index=False, encoding="utf-8-sig")
    pd.DataFrame(qual_rows).to_csv(os.path.join(out_dir, "quality_top20.csv"),
                                   index=False, encoding="utf-8-sig")
    pd.DataFrame(qual_removed).to_csv(os.path.join(out_dir, "quality_removed.csv"),
                                      index=False, encoding="utf-8-sig")
    print(f"持仓明细 {len(holdings_rows)} 行 · 剔除记录 {len(removed_rows)} 行 · "
          f"质量Top20 成分 {len(qual_rows)} 行 · 质量剔除 {len(qual_removed)} 行", flush=True)
    nav = pd.DataFrame({"策略": (1 + strat).cumprod(), "动量轮动策略（等权）": (1 + equal).cumprod(),
                        "质量Top20等权": (1 + qual).cumprod()})
    if bench_eq is not None:
        nav = nav.join(bench_eq)
    nav.to_csv(os.path.join(out_dir, "nav.csv"), encoding="utf-8-sig")
    print("\n已保存 backtest_summary.csv / holdings.csv / nav.csv", flush=True)


if __name__ == "__main__":
    main()
