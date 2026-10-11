# -*- coding: utf-8 -*-
"""按申万三级行业生成季度股池：每个细分行业取评分前 5 名，不足 5 只不补入。"""
import sys, os, json
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = r"C:\Users\12066\WorkBuddy\2026-10-04-19-37-33"

TOPN = 5

# 定期报告披露截止日：一季报 4/30、中报 8/31、三季报 10/31
# → 信息可得日取「截止次月首日」，避免未来函数
_ASOF_MONTH = {"03-31": "05-01", "06-30": "09-01", "09-30": "11-01", "12-31": "05-01"}


def asof_of(end: str):
    """报告期 → 信息可得日（截至该日全部 A 股已披露完毕）"""
    end = str(end)
    mmdd = end[5:10]
    if mmdd == "12-31":                       # 年报截止 4/30 → 次月首日 5/1（次年）
        return f"{int(end[:4]) + 1}-05-01"
    return f"{end[:4]}-{_ASOF_MONTH.get(mmdd, '05-01')}"


ASOF = {p: asof_of(p) for p in ["2024-03-31", "2024-06-30", "2024-09-30",
                                "2025-03-31", "2025-06-30", "2025-09-30",
                                "2026-03-31", "2026-06-30"]}


def build(df=None):
    if df is None:
        df = pd.read_csv(os.path.join(BASE, "data", "scores.csv"), dtype={"code": str})
    df = df[df["FAQ_score"].notna()].copy()
    pools = {}
    rows = []
    for end, g in df.groupby("EndDate"):
        g = g.sort_values("FAQ_score", ascending=False)
        sel = g.groupby("sw3").head(TOPN).copy()
        sel["rank_in_industry"] = sel.groupby("sw3").cumcount() + 1
        sel = sel.sort_values(["sw3", "rank_in_industry"])
        pools[end] = {
            "asof": asof_of(end),
            "label": g["报告期"].iloc[0],
            "members": sel[["code", "name", "sw3", "sw1", "FAQ_score", "rank_in_industry",
                            "mktcap"]].to_dict("records"),
        }
        for r in sel.to_dict("records"):
            rows.append(r)
        print(f"{end} {g['报告期'].iloc[0]}: 行业数={sel['sw3'].nunique()} 入选={len(sel)}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(BASE, "data", "pool_members.csv"), index=False, encoding="utf-8-sig")
    json.dump(pools, open(os.path.join(BASE, "data", "pools.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    allcodes = sorted(out["code"].unique())
    json.dump(allcodes, open(os.path.join(BASE, "scripts", "codes_pool.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print("\n股池个股数(并集):", len(allcodes))
    return pools, out


if __name__ == "__main__":
    build()
