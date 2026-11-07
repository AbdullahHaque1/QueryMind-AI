"""Draw the report figures from results/results.json.   python -m experiments.make_figures
(needs matplotlib: pip install matplotlib)"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from src import config

R = json.loads((config.ROOT / "results" / "results.json").read_text(encoding="utf-8"))
OUT = config.ROOT / "results" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"font.family": ["Liberation Serif", "DejaVu Serif"],
                     "font.size": 7.5, "axes.linewidth": 0.6, "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.dpi": 300})
W = 3.05
BLUE, ORANGE, GREY, GREEN, RED = "#2b5c8a", "#d9822b", "#8a8a8a", "#3b7d4f", "#b03a2e"


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


# Figure 1 - pipeline
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(W, 3.9))
    ax.set_xlim(0, 10); ax.set_ylim(0, 13); ax.axis("off")

    def box(x, y, w, h, text, fc="#eef3f8", ec=BLUE):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.25",
                                    fc=fc, ec=ec, lw=0.8))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=7)

    def arrow(x1, y1, x2, y2, **kw):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", lw=0.8, color="#333", **kw))

    box(1.5, 11.6, 7, 1.1, "Question in plain English")
    box(0.5, 9.3, 9, 1.5, "Prompt builder\nschema from sqlite_master + k similar solved examples")
    box(0.5, 7.2, 4.2, 1.3, "LLM\n(OpenAI API)", fc="#fdf1e3", ec=ORANGE)
    box(5.3, 7.2, 4.2, 1.3, "Demo matcher\n(examples.json)", fc="#fdf1e3", ec=ORANGE)
    box(0.5, 5.3, 9, 1.2, "Layer 1: static check (one SELECT only)", fc="#e9f3ec", ec=GREEN)
    box(0.5, 3.0, 9, 1.8, "Layers 2-4: read-only connection,\nauthorizer, row cap, time limit", fc="#e9f3ec", ec=GREEN)
    box(1.0, 0.7, 8, 1.4, "SQL text + result table\n(CLI or Streamlit)")
    arrow(5, 11.6, 5, 10.8); arrow(2.6, 9.3, 2.6, 8.5); arrow(7.4, 9.3, 7.4, 8.5)
    arrow(2.6, 7.2, 2.6, 6.5); arrow(7.4, 7.2, 7.4, 6.5)
    arrow(5, 5.3, 5, 4.8); arrow(5, 3.0, 5, 2.1)
    ax.annotate("", xy=(0.45, 7.85), xytext=(0.45, 3.9),
                arrowprops=dict(arrowstyle="-|>", lw=0.7, color=RED, ls="--",
                                connectionstyle="arc3,rad=-0.45"))
    ax.text(-0.15, 5.9, "retry\n(error text)", fontsize=6, color=RED, ha="right", va="center")
    save(fig, "fig1_pipeline.png")


# Figure 2 - safety ablation
def fig_safety():
    cfg = R["safety"]["configs"]
    names = list(cfg.keys())
    fig, ax = plt.subplots(figsize=(W, 2.5))
    y = range(len(names))
    ax.barh([i + 0.2 for i in y], [cfg[n]["executed"] for n in names], 0.38, color=ORANGE, label="statement executed")
    ax.barh([i - 0.2 for i in y], [cfg[n]["modified"] for n in names], 0.38, color=RED, label="database changed")
    ax.set_yticks(list(y)); ax.set_yticklabels(names, fontsize=7); ax.invert_yaxis()
    ax.set_xlabel(f"out of {R['safety']['n_attacks']} hostile statements")
    for i, n in enumerate(names):
        ax.text(cfg[n]["executed"] + 0.4, i + 0.2, str(cfg[n]["executed"]), va="center", fontsize=6.5)
        ax.text(cfg[n]["modified"] + 0.4, i - 0.2, str(cfg[n]["modified"]), va="center", fontsize=6.5)
    ax.legend(frameon=False, fontsize=6.5, loc="lower right")
    save(fig, "fig2_safety.png")


# Figure 3 - threshold sweep
def fig_sweep():
    sw = R["matcher"]["sweep"]
    t = [s["threshold"] for s in sw]
    n, o = sw[0]["inscope_total"], sw[0]["oos_total"]
    fig, ax = plt.subplots(figsize=(W, 2.3))
    ax.plot(t, [100 * s["correct"] / n for s in sw], "-o", ms=2.5, color=GREEN, label="paraphrase: correct")
    ax.plot(t, [100 * s["wrong"] / n for s in sw], "-s", ms=2.5, color=RED, label="paraphrase: wrong SQL")
    ax.plot(t, [100 * s["missed"] / n for s in sw], "-^", ms=2.5, color=GREY, label="paraphrase: refused")
    ax.plot(t, [100 * s["oos_accepted"] / o for s in sw], "--d", ms=2.5, color=ORANGE, label="out-of-scope: answered")
    ax.axvline(R["matcher"]["default_threshold"], color="#333", lw=0.6, ls=":")
    ax.text(0.555, 96, "default", fontsize=6.5, va="top")
    ax.set_xlabel("similarity threshold"); ax.set_ylabel("% of questions"); ax.set_ylim(-2, 100)
    ax.legend(frameon=False, fontsize=6, loc="center left", bbox_to_anchor=(0.0, 0.62))
    save(fig, "fig3_threshold_sweep.png")


# Figure 4 - score strips
def fig_scores():
    m = R["matcher"]
    rows = [("easy", [r["score"] for r in m["inscope"] if r["difficulty"] == "easy"], GREEN),
            ("medium", [r["score"] for r in m["inscope"] if r["difficulty"] == "medium"], BLUE),
            ("hard", [r["score"] for r in m["inscope"] if r["difficulty"] == "hard"], GREY),
            ("out of scope", [r["score"] for r in m["oos"]], ORANGE)]
    fig, ax = plt.subplots(figsize=(W, 1.9))
    for i, (lab, xs, c) in enumerate(rows):
        ax.scatter(xs, [i] * len(xs), s=14, color=c, alpha=0.85, edgecolor="white", lw=0.3)
    ax.axvline(m["default_threshold"], color="#333", lw=0.6, ls=":")
    ax.set_yticks(range(4)); ax.set_yticklabels([r[0] for r in rows]); ax.invert_yaxis()
    ax.set_xlim(0.1, 0.95); ax.set_xlabel("best similarity score")
    save(fig, "fig4_score_strips.png")


# Figure 5 - row cap
def fig_rowcap():
    rc = R["limits"]["row_cap"]; full = R["limits"]["row_cap_unguarded"]
    labels = [str(r["cap"]) for r in rc] + ["no cap\n(40,000)"]
    vals = [r["median_ms"] for r in rc] + [full["ms"]]
    fig, ax = plt.subplots(figsize=(W, 2.0))
    bars = ax.bar(labels, vals, color=[BLUE] * len(rc) + [RED], width=0.6)
    ax.set_yscale("log"); ax.set_ylabel("time (ms, log scale)"); ax.set_xlabel("rows returned")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.12, f"{v:.2f}", ha="center", fontsize=6.5)
    ax.set_ylim(0.08, 150)
    save(fig, "fig5_row_cap.png")


# Figure 6 - latency
def fig_latency():
    L = R["latency"]
    labels = ["validate_select\n(layer 1 only)", "unguarded\nquery", "guarded\nrun_query"]
    med = [L["validate_us"]["median"] / 1000, L["raw_ms"]["median"], L["guarded_ms"]["median"]]
    p95 = [L["validate_us"]["p95"] / 1000, L["raw_ms"]["p95"], L["guarded_ms"]["p95"]]
    fig, ax = plt.subplots(figsize=(W, 2.0))
    x = range(3)
    ax.bar([i - 0.19 for i in x], med, 0.36, color=BLUE, label="median")
    ax.bar([i + 0.19 for i in x], p95, 0.36, color=ORANGE, label="95th percentile")
    for i in x:
        ax.text(i - 0.19, med[i] * 1.05, f"{med[i]:.3f}", ha="center", fontsize=6)
        ax.text(i + 0.19, p95[i] * 1.05, f"{p95[i]:.3f}", ha="center", fontsize=6)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=6.5)
    ax.set_ylabel("milliseconds"); ax.legend(frameon=False, fontsize=6.5)
    ax.set_ylim(0, max(p95) * 1.25)
    save(fig, "fig6_latency.png")


if __name__ == "__main__":
    for f in (fig_pipeline, fig_safety, fig_sweep, fig_scores, fig_rowcap, fig_latency):
        f()
    print("figures saved to", OUT)
