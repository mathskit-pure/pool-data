# -*- coding: utf-8 -*-
"""
舞弊调整质量因子评分模型 (Fraud-Adjusted Quality, FAQ)
=========================================================
理论依据
[1] Hsu, Kalesnik & Kose《什么是质量？》
    七大质量特征中，仅 4 类通过"三步因子稳健性检验"：
      盈利能力 / 会计质量 / 分红·股权稀释 / 投资活动   → 有效溢价来源
      盈利稳定性 / 资本结构  → 实为低波(low-beta)变体，冗余
      盈利增长              → 无文献支持
[2] Chen, Bu, Fang & Xu《一种经欺诈概率调整的新质量因子 (fmQMJ)》
    Score = 质量分 − 标准化舞弊概率
    舞弊实施概率 ↑：关联交易、股权质押、CEO股权激励
    舞弊实施概率 ↓：管理层持股、高质量审计

评分流程（每个报告期截面内）
    原始指标 → 1%/99% 缩尾 → 申万一级行业内中位数中心化 → z-score(±3)
    → 四支柱加权得 质量分 Q → 舞弊信号加权得 舞弊风险 F
    → FAQ = Q − λ·F
"""
import sys, os, json
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = r"C:\Users\12066\WorkBuddy\2026-10-04-19-37-33"
RAW = os.path.join(BASE, "data", "raw")

# 评分起点（含）；仅取一季报 / 中报 / 三季报，年报(12-31)不评分
FIRST_PERIOD = "2024-03-31"
QTR_LABEL = {"03": "一季报", "06": "中报", "09": "三季报", "12": "年报"}

# 首次运行时的固定清单；后续若数据中出现更晚的报告期会自动纳入（见 main）
BASE_PERIODS = ["2024-03-31", "2024-06-30", "2024-09-30",
                "2025-03-31", "2025-06-30", "2025-09-30",
                "2026-03-31", "2026-06-30"]

NUM = lambda s: pd.to_numeric(s, errors="coerce")
LAMBDA = 1.0          # 舞弊调整强度（fmQMJ：减去标准化舞弊概率）


def load():
    def rd(name):
        return pd.read_csv(os.path.join(RAW, name), dtype=str,
                           engine="python", on_bad_lines="skip")
    inc, bal, cf = rd("income.csv"), rd("balance.csv"), rd("cashflow.csv")
    for df in (inc, bal, cf):
        df["EndDate"] = df["EndDate"].astype(str).str.strip()
        df["key"] = df["code"] + "|" + df["EndDate"]
    return inc, bal, cf


def build_panel(inc, bal, cf):
    inc = inc.drop_duplicates("key").set_index("key")
    bal = bal.drop_duplicates("key").set_index("key")
    cf = cf.drop_duplicates("key").set_index("key")
    idx = sorted(set(inc.index) & set(bal.index) & set(cf.index))

    def col(df, n):
        return NUM(df[n]) if n in df.columns else pd.Series(np.nan, index=df.index)

    p = pd.DataFrame(index=pd.MultiIndex.from_tuples(
        [tuple(k.split("|")) for k in idx], names=["code", "EndDate"]))

    p["roe_ttm"] = col(inc, "ROETTM").reindex(idx).values
    p["roa_ttm"] = col(inc, "ROATTM").reindex(idx).values
    p["roic"] = col(inc, "ROIC").reindex(idx).values
    p["gross_margin"] = col(inc, "GrossIncomeRatio").reindex(idx).values
    p["net_margin"] = col(inc, "NetProfitRatio").reindex(idx).values
    p["ni_ttm"] = col(inc, "NPParentCompanyOwnersTTM").reindex(idx).values
    p["ni"] = col(inc, "NPParentCompanyOwners").reindex(idx).values
    p["rev_ttm"] = col(inc, "OperatingRevenueTTM").reindex(idx).values
    p["div_ttm"] = col(inc, "DividendTTM").reindex(idx).values
    p["deduct"] = col(inc, "NPDeductNonRecurringPL").reindex(idx).values
    p["op_cost"] = col(inc, "OperatingCost").reindex(idx).values

    p["cur_assets"] = col(bal, "TotalCurrentAssets").reindex(idx).values
    p["noncur_assets"] = col(bal, "TotalNonCurrentAssets").reindex(idx).values
    p["total_assets"] = p["cur_assets"] + p["noncur_assets"]
    p["debt_assets"] = col(bal, "DebtAssetsRatio").reindex(idx).values
    p["goodwill"] = col(bal, "GoodWill").reindex(idx).values
    p["inv_tr"] = col(bal, "InventoryTRate").reindex(idx).values
    p["ar_tr"] = col(bal, "ARTRate").reindex(idx).values
    p["naps"] = col(bal, "NAPS").reindex(idx).values
    p["se"] = col(bal, "SEWithoutMI").reindex(idx).values

    p["cfo_ttm"] = col(cf, "NetOperateCashFlowTTM").reindex(idx).values

    p = p.reset_index()
    p["pdate"] = pd.to_datetime(p["EndDate"])
    return p.sort_values(["code", "pdate"]).reset_index(drop=True)


def add_derived(p):
    g = p.groupby("code")
    L = lambda c: g[c].shift(4)          # 同比滞后 4 个季度

    def sd(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        return np.where((b == 0) | ~np.isfinite(b) | ~np.isfinite(a), np.nan, a / b)

    p["total_assets_y"] = L("total_assets")
    p["rev_ttm_y"] = L("rev_ttm")
    p["gross_margin_y"] = L("gross_margin")
    p["debt_assets_y"] = L("debt_assets")
    p["naps_y"] = L("naps")
    p["se_y"] = L("se")

    p["cash_conversion"] = sd(p["cfo_ttm"], p["ni_ttm"])                 # 净利现金含量
    p["ni_quality"] = np.where(p["ni"] != 0, sd(p["deduct"], p["ni"]), np.nan)  # 扣非/归母
    p["accruals_ttm"] = p["ni_ttm"] - p["cfo_ttm"]
    p["tata"] = sd(p["accruals_ttm"], p["total_assets"])                 # Sloan 总应计

    p["ar"] = np.where(p["ar_tr"] > 0, p["rev_ttm"] / p["ar_tr"], np.nan)
    p["inv"] = np.where(p["inv_tr"] > 0, p["op_cost"] / p["inv_tr"], np.nan)
    p["ar_y"] = L("ar")

    p["payout"] = np.where(p["ni_ttm"] > 0, sd(p["div_ttm"], p["ni_ttm"]), np.nan)
    p["dividend_yield_proxy"] = np.where(p["se"] > 0, sd(p["div_ttm"], p["se"]), np.nan)
    p["shares"] = np.where(p["naps"] > 0, p["se"] / p["naps"], np.nan)
    p["shares_y"] = np.where(p["naps_y"] > 0, p["se_y"] / p["naps_y"], np.nan)
    p["share_growth"] = np.where((p["shares_y"] > 0) & p["shares"].notna(),
                                 p["shares"] / p["shares_y"] - 1, np.nan)

    p["asset_growth"] = np.where(p["total_assets_y"] > 0,
                                 p["total_assets"] / p["total_assets_y"] - 1, np.nan)
    p["inv_growth"] = np.where(L("inv") > 0, p["inv"] / L("inv") - 1, np.nan)

    # Beneish 式舞弊代理变量（全部可由三大表观测）
    p["dsri"] = np.where((p["ar_y"] > 0) & (p["rev_ttm_y"] > 0),
                         sd(p["ar"] / p["rev_ttm"], p["ar_y"] / p["rev_ttm_y"]), np.nan)
    p["gmi"] = np.where(p["gross_margin"] > 0, p["gross_margin_y"] / p["gross_margin"], np.nan)
    p["sgi"] = np.where(p["rev_ttm_y"] > 0, p["rev_ttm"] / p["rev_ttm_y"], np.nan)
    p["lvgi"] = np.where(p["debt_assets_y"] > 0, p["debt_assets"] / p["debt_assets_y"], np.nan)
    nc = sd(p["noncur_assets"], p["total_assets"])
    ncy = sd(L("noncur_assets"), p["total_assets_y"])
    p["aqi"] = np.where(ncy > 0, nc / ncy, np.nan)
    p["goodwill_ratio"] = sd(p["goodwill"], p["total_assets"])
    return p


# ── 信号定义 ────────────────────────────────────────────────────────────────
PILLARS = {
    "盈利能力":  [("roe_ttm", +1), ("roic", +1), ("roa_ttm", +1),
                ("gross_margin", +1), ("net_margin", +1), ("cash_conversion", +1)],
    "会计质量":  [("tata", -1), ("dsri", -1), ("aqi", -1), ("ni_quality", +1)],
    "分红与稀释": [("payout", +1), ("dividend_yield_proxy", +1), ("share_growth", -1)],
    "投资活动":  [("asset_growth", -1), ("inv_growth", -1)],
}
PILLAR_W = {"盈利能力": 0.34, "会计质量": 0.22, "分红与稀释": 0.22, "投资活动": 0.22}
FRAUD = [("tata", +1), ("dsri", +1), ("aqi", +1), ("sgi", +1),
         ("gmi", +1), ("lvgi", +1), ("goodwill_ratio", +1), ("share_growth", +1)]


def zscore_ind_neutral(p, col):
    """截面内：缩尾 → 申万一级行业中位数中心化 → z-score → ±3 截尾"""
    out = pd.Series(np.nan, index=p.index)
    for _, gdf in p.groupby("EndDate"):
        s = pd.to_numeric(gdf[col], errors="coerce")
        if s.notna().sum() < 20:
            continue
        s = s.clip(s.quantile(0.01), s.quantile(0.99))
        med = s.groupby(gdf["sw1"]).transform("median")
        s = s - med
        mu, sdv = s.mean(), s.std(ddof=0)
        if np.isfinite(sdv) and sdv > 0:
            out.loc[gdf.index] = ((s - mu) / sdv).clip(-3, 3)
    return out


def main():
    meta = json.load(open(os.path.join(BASE, "scripts", "meta.json"), encoding="utf-8"))
    big = json.load(open(os.path.join(BASE, "scripts", "codes_big.json"), encoding="utf-8"))
    caps = json.load(open(os.path.join(BASE, "data", "caps.json"), encoding="utf-8"))
    universe = set(big)

    inc, bal, cf = load()
    p = build_panel(inc, bal, cf)
    p = add_derived(p)
    p["sw1"] = p["code"].map(lambda c: meta.get(c, {}).get("sw1") or "未分类")
    p["sw2"] = p["code"].map(lambda c: meta.get(c, {}).get("sw2") or "未分类")
    p["sw3"] = p["code"].map(lambda c: meta.get(c, {}).get("sw3") or "未分类")
    p["name"] = p["code"].map(lambda c: meta.get(c, {}).get("name") or c)
    p["mktcap"] = p["code"].map(lambda c: caps.get(c))
    print("panel:", p.shape, "codes:", p["code"].nunique(), flush=True)

    # 仅保留标的池内个股
    p = p[p["code"].isin(universe)].copy()
    print("universe filtered:", p["code"].nunique(), flush=True)

    Z = {}
    for sigs in list(PILLARS.values()) + [FRAUD]:
        for c, _ in sigs:
            if c not in Z:
                Z[c] = zscore_ind_neutral(p, c)

    for pillar, sigs in PILLARS.items():
        mat = pd.concat([(Z[c] * d).rename(c) for c, d in sigs], axis=1)
        p["P_" + pillar] = mat.mean(axis=1, skipna=True)

    q = pd.Series(0.0, index=p.index)
    wsum = pd.Series(0.0, index=p.index)
    for pillar, w in PILLAR_W.items():
        v = p["P_" + pillar]
        ok = v.notna()
        q[ok] += w * v[ok]
        wsum[ok] += w
    p["Q_score"] = np.where(wsum > 0, q / wsum, np.nan)

    fmat = pd.concat([(Z[c] * d).rename(c) for c, d in FRAUD], axis=1)
    p["F_score"] = fmat.mean(axis=1, skipna=True)

    def restd(s):
        out = pd.Series(np.nan, index=p.index)
        for _, gdf in p.groupby("EndDate"):
            v = s.loc[gdf.index]
            if v.notna().sum() < 20:
                continue
            sdv = v.std(ddof=0)
            out.loc[gdf.index] = ((v - v.mean()) / sdv).clip(-3, 3) if sdv else 0.0
        return out

    p["Q_z"] = restd(p["Q_score"])
    p["F_z"] = restd(p["F_score"])
    p["FAQ_score"] = p["Q_z"] - LAMBDA * p["F_z"]
    p["FAQ_pct"] = p.groupby("EndDate")["FAQ_score"].rank(pct=True) * 100

    # 报告期：面板中 2024-03-31 及之后的所有季报（剔除年报），自动纳入更新的季度
    avail = sorted({d for d in p["EndDate"].dropna().unique()
                    if str(d) >= FIRST_PERIOD and str(d)[5:7] != "12"})
    TARGET_PERIODS = sorted(set(avail) | {x for x in BASE_PERIODS if x in set(p["EndDate"])})
    PERIOD_LABEL = {k: f"{k[:4]}年" + QTR_LABEL.get(k[5:7], "") for k in TARGET_PERIODS}
    out = p[p["EndDate"].isin(TARGET_PERIODS)].copy()
    out["报告期"] = out["EndDate"].map(PERIOD_LABEL)
    keep = ["code", "name", "EndDate", "报告期", "sw1", "sw2", "sw3", "mktcap",
            "Q_score", "F_score", "Q_z", "F_z", "FAQ_score", "FAQ_pct",
            "P_盈利能力", "P_会计质量", "P_分红与稀释", "P_投资活动",
            "roe_ttm", "roic", "roa_ttm", "gross_margin", "net_margin", "cash_conversion",
            "tata", "dsri", "aqi", "sgi", "gmi", "lvgi", "goodwill_ratio",
            "payout", "share_growth", "asset_growth", "ni_quality"]
    out = out[keep].sort_values(["EndDate", "FAQ_score"], ascending=[True, False])
    out.to_csv(os.path.join(BASE, "data", "scores.csv"), index=False, encoding="utf-8-sig")
    print("\n评分完成:", out.shape)
    print(out.groupby("报告期")["FAQ_score"].agg(["count", "mean", "std"]), flush=True)
    return out


if __name__ == "__main__":
    main()
