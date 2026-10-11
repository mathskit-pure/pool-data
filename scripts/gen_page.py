# -*- coding: utf-8 -*-
"""生成「舞弊调整质量因子 · 季度动态股池」展示页面（单文件 HTML，浅色主题）。"""
import sys, os, json, html
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = r"C:\Users\12066\WorkBuddy\2026-10-04-19-37-33"
OUT = os.path.join(BASE, "data", "pool_page.html")

# 页面按报告期升序展示；若数据中出现更新的报告期会自动排在最前
ORDER = ["2024-03-31", "2024-06-30", "2024-09-30", "2025-03-31", "2025-06-30",
         "2025-09-30", "2026-03-31", "2026-06-30"]


def ordered(pools):
    keys = [p for p in ORDER if p in pools]
    keys += sorted(k for k in pools if k not in ORDER)
    return keys


def svg_chart(nav):
    """内嵌 SVG 折线图（无外部依赖）"""
    if nav is None or nav.empty:
        return "<p class='muted'>暂无净值数据</p>"
    cols = [c for c in nav.columns if nav[c].notna().any()]
    if not cols:
        return ""
    W, H, PL, PR, PT, PB = 950, 340, 56, 180, 24, 34
    sub = nav[cols].dropna(how="all")
    vmin = float(sub.min().min()); vmax = float(sub.max().max())
    if vmax == vmin:
        vmax = vmin + 0.01
    n = len(sub)
    xs = [PL + (W - PL - PR) * i / max(1, n - 1) for i in range(n)]

    def y(v):
        return PT + (H - PT - PB) * (vmax - v) / (vmax - vmin)

    colors = {"策略": "#c0392b", "动量轮动策略（等权）": "#2c6f9e", "质量Top20等权": "#0f9d58",
              "沪深300": "#7a7a7a", "创业板50": "#e08a1e", "科创50": "#8e44ad"}
    parts = [f"<svg viewBox='0 0 {W} {H}' class='chart' role='img'>"]
    for k in range(5):
        val = vmin + (vmax - vmin) * k / 4
        yy = y(val)
        parts.append(f"<line x1='{PL}' y1='{yy:.1f}' x2='{W-PR}' y2='{yy:.1f}' stroke='#e6e8eb'/>")
        parts.append(f"<text x='{PL-8}' y='{yy+4:.1f}' text-anchor='end' font-size='11' fill='#6b7280'>{val:.2f}</text>")
    for i, c in enumerate(cols):
        s = sub[c].ffill()
        pts = " ".join(f"{xs[j]:.1f},{y(float(s.iloc[j])):.1f}" for j in range(n))
        col = colors.get(c, ["#c0392b", "#2c6f9e", "#0f9d58",
                             "#7a7a7a", "#e08a1e", "#8e44ad"][i % 6])
        parts.append(f"<polyline points='{pts}' fill='none' stroke='{col}' stroke-width='2'/>")
        lx = W - PR + 12
        ly = PT + 18 + i * 22
        parts.append(f"<line x1='{lx}' y1='{ly}' x2='{lx+18}' y2='{ly}' stroke='{col}' stroke-width='3'/>")
        parts.append(f"<text x='{lx+24}' y='{ly+4}' font-size='12' fill='#374151'>{html.escape(str(c))}</text>")
    idx = sub.index
    for j in [0, n // 3, 2 * n // 3, n - 1]:
        if j < 0 or j >= n:
            continue
        d = pd.Timestamp(idx[j]).strftime("%y-%m")
        parts.append(f"<text x='{xs[j]:.1f}' y='{H-12}' text-anchor='middle' font-size='11' fill='#6b7280'>{d}</text>")
    parts.append("</svg>")
    return "".join(parts)


def main():
    pools = json.load(open(os.path.join(BASE, "data", "pools.json"), encoding="utf-8"))
    caps = json.load(open(os.path.join(BASE, "data", "caps.json"), encoding="utf-8"))

    nav = None
    if os.path.exists(os.path.join(BASE, "data", "nav.csv")):
        nav = pd.read_csv(os.path.join(BASE, "data", "nav.csv"), index_col=0)
        nav.index = pd.to_datetime(nav.index)
    summ = None
    if os.path.exists(os.path.join(BASE, "data", "backtest_summary.csv")):
        summ = pd.read_csv(os.path.join(BASE, "data", "backtest_summary.csv"))
    hold = None
    if os.path.exists(os.path.join(BASE, "data", "holdings.csv")):
        hold = pd.read_csv(os.path.join(BASE, "data", "holdings.csv"), dtype={"代码": str})
    rm = None
    if os.path.exists(os.path.join(BASE, "data", "removed.csv")):
        rm = pd.read_csv(os.path.join(BASE, "data", "removed.csv"), dtype={"代码": str})
    q20 = None
    if os.path.exists(os.path.join(BASE, "data", "quality_top20.csv")):
        q20 = pd.read_csv(os.path.join(BASE, "data", "quality_top20.csv"), dtype={"代码": str})

    periods = ordered(pools)   # 升序；最新一期排最后，各期默认收起
    n_big = sum(1 for c in caps.values() if c >= 300e8)
    total_codes = len({m["code"] for p in periods for m in pools[p]["members"]})
    n_ind = len({m["sw3"] for p in periods for m in pools[p]["members"]})

    pool_html = []
    for p in periods:
        v = pools[p]
        mem = v["members"]
        by_ind = {}
        for m in mem:
            by_ind.setdefault(m["sw3"], []).append(m)
        groups = sorted(by_ind.items(), key=lambda kv: -len(kv[1]))
        pool_html.append(
            f"<section class='card'><div class='card-h'><h3>{html.escape(v['label'])}"
            f"<span class='pill'>信息可得 {v['asof']}</span></h3>"
            f"<span class='muted'>{len(mem)} 只 · {len(by_ind)} 个申万三级行业</span></div>")
        pool_html.append("<details>"
                         f"<summary>展开 / 收起（{len(by_ind)} 个行业 · {len(mem)} 只）</summary>"
                         "<div class='grid'>")
        for ind, ms in groups:
            pool_html.append("<div class='ind'><div class='ind-h'>"
                             f"<span class='ind-name'>{html.escape(ind)}</span>"
                             f"<span class='muted'>{len(ms)} 只</span></div>")
            pool_html.append("<table class='mini'><thead><tr><th>#</th><th>代码</th><th>名称</th>"
                             "<th>评分</th><th>市值(亿)</th></tr></thead><tbody>")
            for i, m in enumerate(ms, 1):
                mc = caps.get(m["code"])
                mcs = f"{mc/1e8:.0f}" if mc else "-"
                pool_html.append(
                    f"<tr><td class='rk'>{i}</td><td class='mono'>{m['code']}</td>"
                    f"<td>{html.escape(m['name'])}</td>"
                    f"<td class='num'>{m['FAQ_score']:.2f}</td><td class='num'>{mcs}</td></tr>")
            pool_html.append("</tbody></table></div>")
        pool_html.append("</div></details></section>")

    bt_html = ""
    if summ is not None and not summ.empty:
        rows = []
        for _, r in summ.iterrows():
            def f(k, pct=True, d=2):
                v = r.get(k)
                if pd.isna(v):
                    return "-"
                return f"{v*100:.{d}f}%" if pct else f"{v:.{d}f}"
            rows.append(f"<tr><td><b>{html.escape(str(r['组合']))}</b></td>"
                        f"<td class='num'>{f('累计收益')}</td><td class='num'>{f('年化收益')}</td>"
                        f"<td class='num'>{f('年化波动')}</td><td class='num'>{f('最大回撤')}</td>"
                        f"<td class='num'>{f('夏普比率', False)}</td>"
                        f"<td class='num'>{f('卡玛比率', False)}</td></tr>")
        bt_html = ("<table class='tbl'><thead><tr><th>组合</th><th>累计收益</th><th>年化收益</th>"
                   "<th>年化波动</th><th>最大回撤</th><th>夏普</th><th>卡玛</th></tr></thead>"
                   f"<tbody>{''.join(rows)}</tbody></table>")

    def pct_span(v, d=2):
        """涨跌幅按 A 股习惯：涨红、跌绿。"""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "<span class='mut'>-</span>"
        col = "up" if v > 0 else ("dn" if v < 0 else "mut")
        sign = "+" if v > 0 else ""
        return f"<span class='{col}'>{sign}{v * 100:.{d}f}%</span>"

    def change_table(days, hold_df, rm_df, n_label, note_map=None):
        """一行一期的持仓变动表：调仓日 | 本期持仓（新增标红）| 本期剔除（标绿+累计涨跌幅）"""
        if hold_df is None or hold_df.empty or not days:
            return "<p class='muted'>暂无数据</p>"
        rows5 = []
        for di, day in enumerate(days):
            h = hold_df[hold_df["调仓日"] == day].sort_values("次序")
            names, n_new = [], 0
            for _, r in h.iterrows():
                nm = html.escape(str(r["名称"]))
                is_new = str(r.get("状态", "")) == "新增"
                n_new += int(is_new)
                names.append(f"<span class='nm-new'>{nm}</span>" if is_new
                             else f"<span class='nm'>{nm}</span>")
            outs, n_out = [], 0
            if rm_df is not None and not rm_df.empty:
                g = rm_df[rm_df["调仓日"] == day].sort_values("区间涨跌幅", ascending=False)
                n_out = len(g)
                for _, r in g.iterrows():
                    outs.append(f"<span class='nm-out'>{html.escape(str(r['名称']))}</span>"
                                f" {pct_span(r['区间涨跌幅'])}")
            tag = "最新一期" if di == 0 else f"倒数第 {di + 1} 期"
            note = f"<span class='cnt'>{(note_map or {}).get(day, '')}</span>" if note_map else ""
            rows5.append(
                f"<tr><td class='day'>{day}<span class='pill'>{tag}</span>{note}</td>"
                f"<td class='cell'>{'、'.join(names)}"
                f"<span class='cnt'>{len(h)} 只 · 新增 {n_new}</span></td>"
                f"<td class='cell'>{'、'.join(outs) if outs else '<span class=\"mut\">—</span>'}"
                f"<span class='cnt'>{n_out} 只</span></td></tr>")
        return (
            "<div class='legend'>"
            "<span class='nm-new'>红色</span> = 本期相较上期新纳入"
            "<span class='nm-out' style='margin-left:14px'>绿色</span> = 本期被剔除，"
            "其后数字为「建仓日 → 剔除日」累计涨跌幅"
            "<span class='mut' style='margin-left:14px'>（涨跌幅按 A 股习惯：红涨绿跌）</span></div>"
            "<table class='tbl tbl5'><thead><tr>"
            f"<th class='c-day'>调仓日</th><th class='c-hold'>本期持仓（{n_label}）</th>"
            "<th class='c-out'>本期剔除（较上期卖出 · 累计涨跌幅）</th>"
            f"</tr></thead><tbody>{''.join(rows5)}</tbody></table>")

    hold_html = ""
    if hold is not None and not hold.empty:
        days_m = sorted(hold["调仓日"].unique())[-5:][::-1]      # 最近 5 期，最新在前
        hold_html = change_table(days_m, hold, rm, "12 只")

    # 质量 Top20：按季度调仓，取最近 5 个季度
    q5_html = ""
    qrm = None
    if os.path.exists(os.path.join(BASE, "data", "quality_removed.csv")):
        qrm = pd.read_csv(os.path.join(BASE, "data", "quality_removed.csv"), dtype={"代码": str})
    if q20 is not None and not q20.empty:
        days_q = sorted(q20["调仓日"].unique())[-5:][::-1]
        note_map = {r["调仓日"]: r["报告期"] for _, r in q20.iterrows()}
        q5_html = change_table(days_q, q20, qrm, "20 只", note_map)

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>舞弊调整质量因子 · 季度动态股池</title>
<style>
:root{{--bg:#f7f8fa;--card:#fff;--bd:#e5e7eb;--tx:#1f2937;--mut:#6b7280;--ac:#c0392b;--ac2:#2c6f9e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);
 font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Inter,sans-serif;line-height:1.6}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:26px;margin:0 0 6px}} h2{{font-size:19px;margin:34px 0 12px}}
h3{{font-size:16px;margin:0}}
.sub{{color:var(--mut);font-size:14px;margin-bottom:18px}}
.card{{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px 18px;margin-bottom:14px}}
.card-h{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px}}
.pill{{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:999px;
 padding:2px 10px;font-size:12px;margin-left:8px;font-weight:400}}
.muted{{color:var(--mut);font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:10px}}
.ind{{border:1px solid var(--bd);border-radius:9px;padding:10px 12px;background:#fcfcfd}}
.ind-h{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}}
.ind-name{{font-weight:600;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
.mini th,.mini td{{padding:4px 6px;text-align:left;border-bottom:1px solid #f1f2f4}}
.tbl th,.tbl td{{padding:8px 10px;text-align:left;border-bottom:1px solid var(--bd)}}
.tbl th{{background:#f3f4f6;font-weight:600}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.tag{{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px;line-height:1.5}}
.tag-new{{background:#fdecea;color:#c0392b;border:1px solid #f5c6c2;font-weight:600}}
.tag-keep{{background:#f3f4f6;color:#6b7280;border:1px solid #e5e7eb}}
.tag-out{{background:#e8f0fb;color:#1d5fa8;border:1px solid #c6d9f2;font-weight:600}}
tr.r-new td{{background:#fdf3f2}}
tr.r-out td{{background:#f2f6fd}}
.up{{color:#c0392b;font-weight:600}} .dn{{color:#128a53;font-weight:600}} .mut{{color:#9ca3af}}
.nm{{color:#374151}} .nm-new{{color:#c0392b;font-weight:600}} .nm-out{{color:#128a53;font-weight:600}}
.tbl5 td{{vertical-align:top;line-height:2}}
.tbl5 .c-day{{width:150px}} .tbl5 .c-hold{{width:38%}}
.tbl5 .day{{white-space:nowrap;font-weight:600}}
.tbl5 .cell{{font-size:13px}}
.tbl5 .cnt{{display:block;color:#9ca3af;font-size:12px;margin-top:4px}}
.sub-h{{font-size:13px;font-weight:600;color:#374151;margin:4px 0 6px}}
.legend{{background:#fcfcfd;border:1px solid var(--bd);border-radius:9px;
 padding:9px 12px;font-size:13px;margin-bottom:12px}}
.mono{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--mut)}}
.rk{{color:var(--mut);width:22px}}
details>summary{{cursor:pointer;color:var(--ac2);font-size:13px;outline:none}}
.chart{{width:100%;height:auto;margin-top:8px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}}
.kpi{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}}
.kpi b{{display:block;font-size:21px;margin-top:2px}}
.kpi span{{color:var(--mut);font-size:12px}}
.note{{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;font-size:13px}}
code{{background:#f3f4f6;padding:1px 6px;border-radius:4px;font-size:12px}}
ol,ul{{padding-left:22px;margin:8px 0}}
li{{margin:4px 0;font-size:14px}}
</style></head><body><div class="wrap">

<h1>舞弊调整质量因子 · 季度动态股池</h1>
<div class="sub">标的池：中证800 + 中证1000 成分股中总市值 ≥ 300 亿元的 {n_big} 只个股（固定清单，不随市值与指数调整变化）
 · 报告期：2024 年一季报 → 2026 年中报 · 更新时点：定期报告披露截止次月首日</div>

<div class="kpis">
 <div class="kpi"><span>评分报告期</span><b>{len(periods)}</b></div>
 <div class="kpi"><span>股池覆盖个股(并集)</span><b>{total_codes}</b></div>
 <div class="kpi"><span>申万三级行业</span><b>{n_ind}</b></div>
 <div class="kpi"><span>动量组合持仓</span><b>12</b></div>
 <div class="kpi"><span>质量Top组合持仓</span><b>20</b></div>
</div>

<h2>一、评分模型：舞弊调整质量因子（fmQMJ 思路）</h2>
<div class="card">
<p><b>质量分 Q</b> —— 依据 Hsu、Kalesnik &amp; Kose《什么是质量？》，七大质量特征中仅四类通过"三步稳健性检验"，
本模型只保留这四类，并按下表权重合成（行业内中位数中心化后取截面 z-score）：</p>
<table class="tbl"><thead><tr><th>支柱</th><th>权重</th><th>信号</th><th>文献依据</th></tr></thead><tbody>
<tr><td><b>盈利能力</b></td><td class="num">34%</td><td>ROE(TTM)、ROIC、ROA(TTM)、毛利率、净利率、净利现金含量</td>
<td>Novy-Marx 2013；Fama-French 2006/2015</td></tr>
<tr><td><b>会计质量</b></td><td class="num">22%</td><td>总应计 TATA、应收偏离 DSRI、资产质量 AQI、扣非/归母</td>
<td>Sloan 1996；Chan-Jegadeesh-Lakonishok 2006</td></tr>
<tr><td><b>分红与稀释</b></td><td class="num">22%</td><td>分红率、股息/权益、股本扩张(负向)</td>
<td>Boudoukh 等 2007；Loughran-Ritter 1995</td></tr>
<tr><td><b>投资活动</b></td><td class="num">22%</td><td>总资产增速(负向)、存货增速(负向)</td>
<td>Titman-Wei-Xie 2004；Cooper-Gulen-Schill 2008</td></tr>
</tbody></table>
<p class="muted">说明：原文证实 <b>盈利稳定性</b> 与 <b>资本结构</b> 实为低波(low-beta)变体、<b>盈利增长</b> 无文献支持，故不纳入质量分。</p>
<p><b>舞弊风险 F</b> —— 依据 Chen、Bu、Fang &amp; Xu《一种经欺诈概率调整的新质量因子》，以财报可观测的操纵代理变量刻画"未被发现的舞弊概率"：
应计异常 TATA、应收/收入偏离 DSRI、软资产 AQI、高增长诱因 SGI、毛利恶化 GMI、杠杆抬升 LVGI、商誉占比、股本扩张。</p>
<p><b>最终评分 FAQ = Q<sub>z</sub> − λ·F<sub>z</sub>（λ = 1.0）</b>：在质量分中扣除标准化舞弊概率，剔除"财报漂亮但操纵风险高"的个股。</p>
</div>

<h2>二、季度股池（申万三级行业各取前 5，不足 5 只不补入）</h2>
{''.join(pool_html)}

<h2>三、动量轮动回测（标的池 = 上述动态股池）</h2>
<div class="card">
<p class="muted">模型来自《龙头动量轮动策略代码更新》：风险调整动量
 <code>Adj = N日平均收益 / √(N日收益方差)</code>；先筛原始动量为正，再按 Adj 取前 L 只；
 权重按 Adj 归一化；权重滞后 1 日（T 日决策、T+1 执行）。<br>
 本页参数：动量周期 N = 10 天，调仓间隔 K = 5 个交易日，持仓 L = 12 只，
 单个申万三级行业最多 2 只（出现第 3 只时剔除动量最低者并按序补录）；回测自 2024-05-06 起。<br><br>
 <b>质量Top20等权组合</b>：不用动量，直接在当期股池内按舞弊调整质量因子得分降序取前 20 只，
 单个申万三级行业最多 2 只（出现第 3 只时跳过其中得分最低者并按序补录）。
 <b>季度买入持有</b>：只在季度股池更新日（信息可得日后的首个交易日）换仓并等权建仓，
 <b>同一季度内不再平衡</b>，权重随价格自然漂移，直到下个季度重新等权建仓；换仓同样权重滞后 1 日。<br><br>
 <b>对比基准</b>：沪深300、创业板50、科创50 三个宽基指数，以及同一动态股池的等权组合；
 基准首日收益不计入，与策略"T 日决策、T+1 执行"对齐。</p>
{bt_html}
<div style="margin-top:14px">{svg_chart(nav)}</div>
</div>

<h2>四、最近五期持仓变动</h2>
<div class="card">
<div class="sub-h" style="font-size:15px">4.1　动量轮动策略（持仓 12 只 · 每 5 个交易日调仓）</div>
{hold_html or '<p class="muted">暂无持仓数据</p>'}
<div class="sub-h" style="font-size:15px;margin-top:26px">4.2　质量Top20等权组合（持仓 20 只 · 季度买入持有）</div>
<div class="note" style="margin-bottom:10px">调仓频率与第三节回测一致：<b>每个季度调仓一次</b>
（调仓日＝报告期信息可得日，如 2026 年中报 → 2026-09-01），同一季度内持仓与成分不变。</div>
{q5_html or '<p class="muted">暂无持仓数据</p>'}
</div>

<h2>五、如何更新最新一季股池</h2>
<div class="card">
<div class="note">A 股定期报告披露截止日：一季报 4/30、中报 8/31、三季报 10/31。
因此在 <b>5 月 1 日 / 9 月 1 日 / 11 月 1 日</b>（披露完成次月首日）可更新对应季度的股池。</div>
<ol>
<li>拉取最新一期三大报表（标的池为固定清单，不随市值与指数成份调整变化）。</li>
<li>用同一套舞弊调整质量因子模型计算该报告期评分。</li>
<li>按申万三级行业取评分前 5，生成新一期股池并写入本页。</li>
<li>以新一期股池替换动量模型的标的池，从"信息可得日"起继续轮动。</li>
</ol>
<p class="muted">已在系统中配置定时更新任务（每年 5 月 1 日、9 月 1 日、11 月 1 日自动执行上述流程）。
如需手动触发，可在对话中提出「更新最新一季股池」。</p>
</div>

<p class="muted" style="margin-top:26px">本页面仅为基于公开财报数据的量化研究展示，不构成任何投资建议。</p>
</div></body></html>"""
    open(OUT, "w", encoding="utf-8").write(doc)
    print("page written:", OUT, len(doc), "chars")


if __name__ == "__main__":
    main()
