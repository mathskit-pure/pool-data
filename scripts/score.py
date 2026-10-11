# -*- coding: utf-8 -*-
"""
FAQ Score — Fraud-Adjusted Quality ( buy-in shares ) scoring engine.

Theory:
  [1] Hsu, Kalesnik & Kose《什么是质量？》 — seven quality categories; only four pass the
      three-step robustness screen: 盈利能力 / 会计质量 / 分红·股权稀释 / 投资活动.
      盈利稳定性 & 资本结构 are merely low-beta variants; 盈利增长 has no literature support.
  [2] Chen, Bu, Fang & Xu《一种经欺诈概率调整的新质量因子》 — fmQMJ = QMJ − standardized
      fraud probability.  Fraud概率 ↑ with 关联交易/股权质押/CEO股权激励,
      ↓ with 管理层持股/高质量审计.

Score = Quality(z) − λ · FraudRisk(z)   within each report period, industry-neutralized.
"""
import sys, os, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE  # noqa: E402  路径：本机 Windows 与云端 Linux 通用

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

RAW = os.path.join(BASE, "data", "raw")

PERIODS = [(y, m) for y in range(2020, 2027) for m in (3, 6, 9, 12)]
PERIOD_KEYS = ["%d-%02d-31" % (y, m) if m in (3, 12) else "%d-%02d-30" % (y, m)
               for (y, m) in PERIODS]
PERIOD_KEYS = [k for k in PERIOD_KEYS if k <= "2026-06-30"]
PERIOD_LABEL = {}
for k in PERIOD_KEYS:
    y, m = int(k[:4]), int(k[5:7])
    PERIOD_LABEL[k] = f"{y}年" + {3: "一季报", 6: "中报", 9: "三季报", 12: "年报"}[m]

NUM = lambda s: pd.to_numeric(s, errors="coerce")


def load():
    def rd(name):
        p = os.path.join(RAW, name)
        return pd.read_csv(p, dtype=str, engine="python", on_bad_lines="skip")
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
    # keep only the targeted 26 fiscal periods
    idx = [k for k in idx if k.split("|")[1] in set(PERIOD_KEYS)]

    def col(df, name):
        return NUM(df[name]) if name in df.columns else pd.Series(np.nan, index=df.index)

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
    p["total_liab"] = col(bal, "TotalLiability").reindex(idx).values
    p["debt_assets"] = col(bal, "DebtAssetsRatio").reindex(idx).values
    p["goodwill"] = col(bal, "GoodWill").reindex(idx).values
    p["inv_tr"] = col(bal, "InventoryTRate").reindex(idx).values
    p["ar_tr"] = col(bal, "ARTRate").reindex(idx).values
    p["naps"] = col(bal, "NAPS").reindex(idx).values
    p["se"] = col(bal, "SEWithoutMI").reindex(idx).values

    p["cfo"] = col(cf, "NetOperateCashFlow").reindex(idx).values
    p["cfo_ttm"] = col(cf, "NetOperateCashFlowTTM").reindex(idx).values
    p["fcff"] = col(cf, "FCFF").reindex(idx).values

    p = p.reset_index()
    p["pdate"] = pd.to_datetime(p["EndDate"])
    p = p.sort_values(["code", "pdate"]).reset_index(drop=True)
    return p


def add_derived(p):
    g = p.groupby("code")
    def safe_div(a, b):
        return np.where((b == 0) | ~np.isfinite(b) | ~np.isfinite(a), np.nan, a / b)

    # YoY lag = 4 quarters
    L = lambda c: g[c].shift(4)

    p["total_assets_y"] = L("total_assets")
    p["rev_ttm_y"] = L("rev_ttm")
    p["gross_margin_y"] = L("gross_margin")
    p["debt_assets_y"] = L("debt_assets")
    p["naps_y"] = L("naps")

    # profitability extras
    p["op_margin"] = safe_div(p["op_profit"] if "op_profit" in p else p["ni"], p["rev_ttm"]) * 100
    p["cash_conversion"] = safe_div(p["cfo_ttm"], p["ni_ttm"])
    p["ni_quality"] = np.where(p["deduct"].notna(), safe_div(p["deduct"], p["ni"]), np.nan)

    # accounting quality / accruals (Sloan 1996)
    p["accruals_ttm"] = p["ni_ttm"] - p["cfo_ttm"]
    p["tata"] = safe_div(p["accruals_ttm"], p["total_assets"])

    # receivables & inventory (derived from turnover ratios)
    p["ar"] = np.where(p["ar_tr"] > 0, p["rev_ttm"] / p["ar_tr"], np.nan)
    p["inv"] = np.where(p["inv_tr"] > 0, p["op_cost"] / p["inv_tr"], np.nan)
    p["ar_y"] = L("ar")

    # payout & dilution
    p["payout"] = np.where(p["ni_ttm"] > 0, safe_div(p["div_ttm"], p["ni_ttm"]), np.nan)
    p["dividend_yield_proxy"] = np.where(p["ni_ttm"] > 0, safe_div(p["div_ttm"], p["se"]), np.nan)
    # share count proxy = equity / net asset per share  →  dilution
    p["shares"] = np.where(p["naps"] > 0, p["se"] / p["naps"], np.nan)
    p["shares_y"] = np.where(p["naps_y"] > 0, L("se") / p["naps_y"], np.nan)
    p["share_growth"] = np.where((p["shares_y"] > 0) & p["shares"].notna(),
                                 p["shares"] / p["shares_y"] - 1, np.nan)

    # investment activity (asset growth — conservative is better)
    p["asset_growth"] = np.where(p["total_assets_y"] > 0,
                                 p["total_assets"] / p["total_assets_y"] - 1, np.nan)
    p["inv_growth"] = np.where(L("inv") > 0, p["inv"] / L("inv") - 1, np.nan)

    # fraud / manipulation signals (Beneish-style, statement observable)
    p["dsri"] = np.where((p["ar_y"] > 0) & (p["rev_ttm_y"] > 0),
                         safe_div(p["ar"] / p["rev_ttm"], p["ar_y"] / p["rev_ttm_y"]), np.nan)
    p["gmi"] = np.where(p["gross_margin"] > 0, p["gross_margin_y"] / p["gross_margin"], np.nan)
    p["sgi"] = np.where(p["rev_ttm_y"] > 0, p["rev_ttm"] / p["rev_ttm_y"], np.nan)
    p["lvgi"] = np.where(p["debt_assets_y"] > 0, p["debt_assets"] / p["debt_assets_y"], np.nan)
    ncur_share = safe_div(p["noncur_assets"], p["total_assets"])
    ncur_share_y = safe_div(L("noncur_assets"), p["total_assets_y"])
    p["aqi"] = np.where(ncur_share_y > 0, ncur_share / ncur_share_y, np.nan)
    p["goodwill_ratio"] = safe_div(p["goodwill"], p["total_assets"])
    return p


# ── signal definitions ────────────────────────────────────────────────────────
# (column, direction)  direction=+1 → higher is better quality
PILLARS = {
    # [1] 盈利能力 — primary driver of the quality premium
    "盈利能力": [("roe_ttm", +1), ("roic", +1), ("roa_ttm", +1),
               ("gross_margin", +1), ("net_margin", +1), ("cash_conversion", +1)],
    # [1] 会计质量 — Sloan(1996): low accruals → high subsequent returns
    "会计质量": [("tata", -1), ("dsri", -1), ("aqi", -1), ("ni_quality", +1)],
    # [1] 分红/股权稀释 — Boudoukh(2007) payout ↑ ; Loughran-Ritter(1995) issuance ↓
    "分红与稀释": [("payout", +1), ("dividend_yield_proxy", +1), ("share_growth", -1)],
    # [1] 投资活动 — Titman-Wei-Xie(2004): conservative asset growth → higher returns
    "投资活动": [("asset_growth", -1), ("inv_growth", -1)],
}
# [2] fraud probability proxies (all oriented: higher = riskier)
FRAUD = [("tata", +1), ("dsri", +1), ("aqi", +1), ("sgi", +1),
         ("gmi", +1), ("lvgi", +1), ("goodwill_ratio", +1), ("share_growth", +1)]

PILLAR_W = {"盈利能力": 0.34, "会计质量": 0.22, "分红与稀释": 0.22, "投资活动": 0.22}
LAMBDA = 1.0


def zscore_industry_neutral(p, col, industry_med = True):
    """Within each report period: winsorise → industry-median-demean → z-score → clip."""
    out = pd.Series(np.nan, index=p.index)
    for d, gdf in p.groupby("EndDate"):
        s = pd.to_numeric(gdf[col], errors="coerce")
        if s.notna().sum() < 20:
            continue
        lo, hi = s.quantile(0.01), s.quantile(0.99)
        s = s.clip(lo, hi)
        if industry_med and p.loc[gdf.index, "sw1"].notna().any():
            med = s.groupby(gdf["sw1"]).transform("median")
            s = s - med
        mu, sd = s.mean(), s.std(ddof=0)
        if not np.isfinite(sd) or sd == 0:
            continue
        out.loc[gdf.index] = ((s - mu) / sd).clip(-3, 3)
    return out


def main():
    meta = json.load(open(os.path.join(BASE, "scripts", "meta.json"), encoding="utf-8"))
    inc, bal, cf = load()
    p = build_panel(inc, bal, cf)
    p = add_derived(p)
    p["sw1"] = p["code"].map(lambda c: meta.get(c, {}).get("sw1"))
    p["sw1"] = p["sw1"].fillna("未分类")
    print("panel:", p.shape, "codes:", p["code"].nunique(),
          "periods:", sorted(p["EndDate"].unique())[-3:], flush=True)

    # standardise every signal once
    Z = {}
    for pillar, sigs in PILLARS.items():
        for c, d in sigs:
            if c not in Z:
                Z[c] = zscore_industry_neutral(p, c)
    for c, d in FRAUD:
        if c not in Z:
            Z[c] = zscore_industry_neutral(p, c)

    # pillar scores: mean of available standardised signals
    for pillar, sigs in PILLARS.items():
        cols = [(c, Z[c] * d) for c, d in sigs]
        mat = pd.concat([v.rename(c) for c, v in cols], axis=1)
        p["P_" + pillar] = mat.mean(axis=1, skipna=True)

    wsum = pd.Series(0.0, index=p.index)
    q = pd.Series(0.0, index=p.index)
    for pillar, w in PILLAR_W.items():
        v = p["P_" + pillar]
        ok = v.notna()
        q[ok] = q[ok] + w * v[ok]
        wsum[ok] = wsum[ok] + w
    p["Q_score"] = np.where(wsum > 0, q / wsum, np.nan)

    fmat = pd.concat([Z[c].rename(c) * d for c, d in FRAUD], axis=1)
    p["F_score"] = fmat.mean(axis=1, skipna=True)

    # re-standardise Q / F per period, then FAQ = Q − λ·F
    def restd(s):
        out = pd.Series(np.nan, index=p.index)
        for d, gdf in p.groupby("EndDate"):
            v = s.loc[gdf.index]
            if v.notna().sum() < 20:
                continue
            mu, sd = v.mean(), v.std(ddof=0)
            out.loc[gdf.index] = ((v - mu) / sd).clip(-3, 3) if sd else 0.0
        return out

    p["Q_z"] = restd(p["Q_score"])
    p["F_z"] = restd(p["F_score"])
    p["FAQ_score"] = p["Q_z"] - LAMBDA * p["F_z"]
    # percentile within period (0–100) for readability
    p["FAQ_pct"] = p.groupby("EndDate")["FAQ_score"].rank(pct=True) * 100
    p["Q_pct"] = p.groupby("EndDate")["Q_score"].rank(pct=True) * 100
    p["F_pct"] = p.groupby("EndDate")["F_score"].rank(pct=True) * 100

    p.to_pickle(os.path.join(BASE, "data", "panel.pkl"))
    print("saved panel.pkl", p.shape, flush=True)
    print(p.groupby("EndDate")["FAQ_score"].count().tail(8), flush=True)


if __name__ == "__main__":
    main()
