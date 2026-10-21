"""Build the frozen normalized-v2 overview and L2RPN figures.

Run from any directory with Python 3.10+ and Matplotlib installed. Inputs are
public evidence only; this script never executes a controller or evaluator.
The eight v1 case objects are preserved exactly, including their anchors.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from pathlib import Path
from statistics import mean, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

BASE = Path(__file__).resolve().parents[1] / "docs/task-cards-v2"
ASSETS = BASE / "assets/normalized-v2"
N_GRID = (0, 1, 3, 5, 10)
COLORS = plt.get_cmap("YlGnBu")
SCALE = Normalize(0, 100)
STATUS_COLORS = {
    "candidate_invalid": "#f2ddd8",
    "terminal_missing": "#e2e2e2",
    "workflow_excluded": "#eee1c8",
    "not_scheduled": "#f3f3f3",
}
STATUS_LABELS = {
    "candidate_invalid": "F",
    "terminal_missing": "M",
    "workflow_excluded": "A",
    "not_scheduled": "NS",
}
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "svg.fonttype": "none",
        "svg.hashsalt": "task-card-normalized-v2",
        "savefig.facecolor": "white",
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> tuple[dict, dict]:
    """Extend immutable v1 with all fifteen retained valid L2RPN grades."""
    previous_path = BASE / "evidence/normalized-v1.json"
    evidence_path = BASE / "evidence/l2rpn.json"
    previous = json.loads(previous_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    assert len(previous["cases"]) == 8
    runs = []
    for record in evidence["records"]:
        assert record["score_valid"] and record["evaluation_completed"]
        assert record["verification"]["runtime_hmac_verified"]
        assert math.isfinite(record["metric"])
        runs.append(
            {
                "n": record["n"],
                "repeat": record["repeat"],
                "raw_value": record["metric"],
                "status": "eligible",
                "source_role": record["role"],
                "workflow_passed": record["workflow_passed"],
                "interrupted_developer_workflow": record["interrupted_developer_workflow"],
                "successful_steps": record["successful_steps"],
                "horizon": record["horizon"],
            }
        )
    assert {(r["n"], r["repeat"]) for r in runs} == {
        (n, repeat) for n in N_GRID for repeat in (1, 2, 3)
    }
    assert len(runs) == 15
    interrupted = [r["source_role"] for r in runs if r["interrupted_developer_workflow"]]
    assert interrupted == ["n1-r3"]
    assert sum(r["workflow_passed"] for r in runs) == 14
    lo, hi = min(r["raw_value"] for r in runs), max(r["raw_value"] for r in runs)
    assert lo < hi
    for run in runs:
        run["normalized"] = 100 * (run["raw_value"] - lo) / (hi - lo)
    groups = []
    for n in N_GRID:
        current = [r for r in runs if r["n"] == n]
        values = [r["normalized"] for r in current]
        groups.append(
            {
                "n": n,
                "planned": 3,
                "eligible": 3,
                "conditional_mean": mean(values),
                "conditional_sample_sd": stdev(values),
                "status_counts": dict(Counter(r["status"] for r in current)),
                "workflow_passed": sum(r["workflow_passed"] for r in current),
                "interrupted_roles": [
                    r["source_role"] for r in current if r["interrupted_developer_workflow"]
                ],
            }
        )
    l2rpn = {
        "id": "l2rpn",
        "label": "L2RPN",
        "card": "l2rpn-grid-control.md",
        "metric": "native economic score S",
        "direction": "higher",
        "source": "l2rpn.json",
        "runs": runs,
        "anchors": {"raw_min": lo, "raw_max": hi, "eligible_count": 15, "frozen_version": "v2"},
        "groups": groups,
        "retention_policy": (
            "All 15 valid retained terminal grades, including interrupted n1-r3; no imputation."
        ),
        "workflow_passed_count": 14,
        "full_episode_completions": 0,
    }
    result = deepcopy(previous)
    result.update(
        schema="task-card-normalized-results-v2",
        version="normalized-v2",
        frozen_at_beijing="2026-10-20",
    )
    result["source_sha256"].update(
        {
            "normalized-v1.json": digest(previous_path),
            "l2rpn.json": digest(evidence_path),
        }
    )
    result["policy"]["inherited_cases"] = (
        "The eight v1 cases, runs, anchors and groups are unchanged."
    )
    result["policy"]["l2rpn_retention"] = l2rpn["retention_policy"]
    result["cases"].append(l2rpn)
    assert result["cases"][:8] == previous["cases"]
    for group, source_group in zip(groups, evidence["groups"]):
        raw = [r["raw_value"] for r in runs if r["n"] == group["n"]]
        assert group["n"] == source_group["n"]
        assert math.isclose(mean(raw), source_group["statistics"]["metric"]["mean"], abs_tol=1e-12)
        assert math.isclose(
            stdev(raw), source_group["statistics"]["metric"]["sample_sd"], abs_tol=1e-12
        )
    return result, evidence


def suffix(run: dict) -> str:
    if run.get("early_stop") or run.get("interrupted_developer_workflow"):
        return "*"
    return "~" if run.get("original_timeout_now_valid") else ""


def draw_cell(
    ax,
    x: int,
    y: int,
    value: float | None,
    label: str,
    detail: str = "",
    status: str = "eligible",
    partial: bool = False,
) -> None:
    color = COLORS(SCALE(value)) if value is not None else STATUS_COLORS.get(status, "#eeeeee")
    ax.add_patch(Rectangle((x - 0.48, y - 0.47), 0.96, 0.94, facecolor=color, edgecolor="none"))
    luminance = (
        sum(w * v for w, v in zip((0.2126, 0.7152, 0.0722), color[:3])) if value is not None else 1
    )
    foreground = "white" if luminance < 0.48 else "#122637"
    if partial:
        ax.add_patch(
            Rectangle(
                (x - 0.48, y - 0.47),
                0.96,
                0.94,
                fill=False,
                hatch="///",
                edgecolor="#8596a3",
                linewidth=0,
            )
        )
    ax.text(
        x,
        y - (0.10 if detail else 0),
        label,
        ha="center",
        va="center",
        color=foreground,
        fontsize=11,
        fontweight="bold",
    )
    if detail:
        ax.text(x, y + 0.22, detail, ha="center", va="center", color=foreground, fontsize=8.5)


def clean_axis(ax, columns: list[str], rows: list[str]) -> None:
    ax.set(xlim=(-0.5, len(columns) - 0.5), ylim=(len(rows) - 0.5, -0.5))
    ax.set_xticks(range(len(columns)), columns)
    ax.set_yticks(range(len(rows)), rows)
    ax.xaxis.tick_top()
    ax.tick_params(length=0, pad=10)
    for spine in ax.spines.values():
        spine.set_visible(False)


def save(fig, stem: str) -> None:
    for extension in ("png", "svg"):
        metadata = (
            {"Date": None, "Creator": "task_card_figures.py"}
            if extension == "svg"
            else {
                "Software": "task_card_figures.py",
            }
        )
        destination = ASSETS / f"{stem}.{extension}"
        fig.savefig(destination, dpi=180, bbox_inches="tight", metadata=metadata)
        if extension == "svg":
            destination.write_text(
                "\n".join(line.rstrip() for line in destination.read_text().splitlines()) + "\n"
            )
    plt.close(fig)


def plot_overview(cases: list[dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(16, 8.6), gridspec_kw={"width_ratios": [1.05, 1]})
    fig.subplots_adjust(left=0.13, right=0.94, top=0.78, bottom=0.21, wspace=0.12)
    for index, ax in enumerate(axes):
        clean_axis(
            ax,
            [f"n = {n}" for n in N_GRID],
            [c["label"] for c in cases] if index == 0 else [""] * len(cases),
        )
        ax.set_title(
            "A. Eligible normalized mean"
            if index == 0
            else "B. Eligible results / planned repeats",
            pad=52,
            loc="left",
            fontweight="bold",
        )
    for y, case in enumerate(cases):
        for x, group in enumerate(case["groups"]):
            if not group["planned"]:
                for ax in axes:
                    draw_cell(ax, x, y, None, "NS", status="not_scheduled")
                continue
            value = group["conditional_mean"]
            label = (
                f"{value:.1f}" if value is not None else "equal" if group["eligible"] else "none"
            )
            star = "*" if group.get("interrupted_roles") else ""
            partial = group["eligible"] != group["planned"]
            draw_cell(
                axes[0],
                x,
                y,
                value,
                label + star,
                f"eligible {group['eligible']}/{group['planned']}",
                partial=partial,
            )
            draw_cell(
                axes[1],
                x,
                y,
                100 * group["eligible"] / group["planned"],
                f"{group['eligible']}/{group['planned']}{star}",
                f"{100 * group['eligible'] / group['planned']:.0f}%",
                partial=partial,
            )
    fig.suptitle(
        "Benchmark results  |  quality and availability",
        x=0.13,
        y=0.97,
        ha="left",
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.13,
        0.915,
        "normalized-v2 | 2026-10-20. Each row has its own frozen observed range; "
        "compare n within a case.",
    )
    fig.text(
        0.13,
        0.13,
        "Hatching: fewer than 3 eligible results. "
        "Eligible availability is not full feasibility or episode survival.",
    )
    fig.text(
        0.13,
        0.085,
        "L2RPN: 15/15 valid terminal grades; 14/15 completed workflows. "
        "* n1-r3 was interrupted; its valid grade is retained.",
        fontsize=9,
    )
    fig.text(
        0.13,
        0.04,
        "The eight v1 rows are unchanged. RTE X15 may be partly feasible; "
        "NS = not scheduled. No cross-case mean or ranking.",
        fontsize=9,
    )
    color_ax = fig.add_axes([0.965, 0.27, 0.012, 0.45])
    fig.colorbar(plt.cm.ScalarMappable(norm=SCALE, cmap=COLORS), cax=color_ax, ticks=[0, 50, 100])
    save(fig, "overview")


def plot_repeats(cases: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(17, 8.2))
    fig.subplots_adjust(left=0.13, right=0.95, top=0.77, bottom=0.22)
    clean_axis(ax, [f"r{r}" for _ in N_GRID for r in (1, 2, 3)], [c["label"] for c in cases])
    for index, n in enumerate(N_GRID):
        ax.text(
            index * 3 + 1,
            1.12,
            f"n = {n}",
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="center",
            fontweight="bold",
            fontsize=12,
        )
        if index:
            ax.axvline(index * 3 - 0.5, color="white", linewidth=6)
    for y, case in enumerate(cases):
        by_slot = {(r["n"], r["repeat"]): r for r in case["runs"]}
        for ni, n in enumerate(N_GRID):
            for repeat in (1, 2, 3):
                run = by_slot.get((n, repeat))
                x = ni * 3 + repeat - 1
                if run is None:
                    draw_cell(ax, x, y, None, "NS", status="not_scheduled")
                    continue
                value = run["normalized"]
                label = (
                    f"{value:.1f}{suffix(run)}"
                    if value is not None
                    else STATUS_LABELS.get(run["status"], "equal")
                )
                detail = f"k={run['feasible_count']}/15" if "feasible_count" in run else ""
                draw_cell(ax, x, y, value, label, detail, run["status"])
    fig.suptitle(
        "Every independent development repeat",
        x=0.13,
        y=0.97,
        ha="left",
        fontsize=18,
        fontweight="bold",
    )
    fig.text(
        0.13,
        0.915,
        "normalized-v2 | 2026-10-20. Terminal artifacts only; "
        "repeat numbers across n do not form paired trials.",
    )
    fig.text(
        0.13,
        0.14,
        "F = invalid candidate     M = missing terminal (developer OOM)     "
        "A = workflow excluded     NS = not scheduled",
    )
    fig.text(
        0.13,
        0.095,
        "* = recorded early stop (MAPDN/PowerGym) or interrupted L2RPN n1-r3; "
        "available valid terminal grades remain included.",
        fontsize=9,
    )
    fig.text(
        0.13,
        0.05,
        "~ = former timeout, valid on uniform HEFTCom regrade. "
        "L2RPN: 15/15 valid grades, 14/15 workflows complete, 0/15 full weeks.",
        fontsize=9,
    )
    save(fig, "repeats")


def plot_l2rpn(evidence: dict) -> None:
    fig, (score_ax, steps_ax) = plt.subplots(
        1, 2, figsize=(13.6, 7.3), gridspec_kw={"width_ratios": [1.3, 1]}
    )
    fig.subplots_adjust(left=0.09, right=0.97, top=0.79, bottom=0.22, wspace=0.28)
    horizon = evidence["protocol"]["case"]["horizon"]
    baseline = max(
        r["metric"]
        for r in evidence["baseline_records"]
        if r["method"] in {"rl_agent", "binbinchen", "lujixiang"}
    )
    score_ax.axhline(baseline, color="#b56a16", linestyle="--", linewidth=1.3)
    score_ax.text(
        0.01,
        0.97,
        f"Best mature baseline S = {baseline:.6f}",
        transform=score_ax.transAxes,
        color="#96540e",
        va="top",
        fontsize=9,
    )
    steps_ax.axhline(horizon, color="#b56a16", linestyle="--", linewidth=1.3)
    steps_ax.text(
        0.02,
        0.96,
        f"Full week = {horizon} successful steps",
        transform=steps_ax.transAxes,
        va="top",
        color="#96540e",
        fontsize=9,
    )
    zoom = steps_ax.inset_axes([0.10, 0.30, 0.83, 0.49])
    zoom.set_title("Zoom: 198-209 successful steps", fontsize=9, pad=5)
    zoom.set_ylim(196, 211)
    zoom.set_yticks([198, 204, 209])
    zoom.grid(axis="y", alpha=0.20)
    for index, n in enumerate(N_GRID):
        records = [r for r in evidence["records"] if r["n"] == n]
        for ax, metric in (
            (score_ax, "metric"),
            (steps_ax, "successful_steps"),
            (zoom, "successful_steps"),
        ):
            values = [r[metric] for r in records]
            ax.errorbar(
                index,
                mean(values),
                yerr=stdev(values),
                fmt="D",
                color="#173342",
                capsize=4,
                markersize=5,
                linewidth=1.25,
                zorder=3,
            )
            for record in records:
                interrupted = record["interrupted_developer_workflow"]
                x = index + (record["repeat"] - 2) * 0.18
                ax.scatter(
                    x,
                    record[metric],
                    marker=("o", "s", "^")[record["repeat"] - 1],
                    facecolors="white" if interrupted else "#26a0a9",
                    edgecolors="#b85825" if interrupted else "#146a7e",
                    s=49,
                    linewidths=1.4,
                    zorder=4,
                )
                if interrupted and ax is score_ax:
                    ax.annotate(
                        "*",
                        (x, record[metric]),
                        xytext=(3, 5),
                        textcoords="offset points",
                        color="#b85825",
                        fontweight="bold",
                        fontsize=13,
                    )
        for ax in (score_ax, steps_ax, zoom):
            ax.set_xlim(-0.5, 4.5)
            ax.set_xticks(range(5), [str(n) for n in N_GRID])
    score_ax.set(
        title="A. Native economic score (higher is better)",
        ylabel="Native score S",
        xlabel="Protected feedback budget n",
    )
    score_ax.set_ylim(-1.5, 0.40)
    score_ax.grid(axis="y", alpha=0.20)
    steps_ax.set(
        title="B. Successful steps in the full week",
        ylabel="Successful real transitions",
        xlabel="Protected feedback budget n",
        ylim=(0, 2200),
    )
    steps_ax.set_yticks([0, 500, 1000, 1500, 2016])
    steps_ax.grid(axis="y", alpha=0.20)
    handles = [
        Line2D(
            [],
            [],
            marker=marker,
            linestyle="none",
            color="#146a7e",
            markerfacecolor="#26a0a9",
            label=f"repeat {i}",
        )
        for i, marker in enumerate(("o", "s", "^"), 1)
    ]
    handles += [
        Line2D([], [], marker="D", color="#173342", label="mean +/- sample SD"),
        Line2D(
            [],
            [],
            marker="^",
            linestyle="none",
            color="#b85825",
            markerfacecolor="white",
            label="interrupted n1-r3*",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.53, 0.115),
        ncol=5,
        frameon=False,
        fontsize=9,
    )
    fig.suptitle(
        "L2RPN  |  retained terminal results on nov26.2",
        x=0.09,
        y=0.97,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.09,
        0.91,
        "All 15 grades are valid native game-over outcomes. "
        "None completed the 2,016-step weekly episode.",
    )
    fig.text(
        0.09,
        0.073,
        "* n1-r3 stopped during development; its valid frozen grade is retained. "
        "Workflow completion: 14/15. Each mean uses 3 grades.",
        fontsize=9,
    )
    fig.text(
        0.09,
        0.026,
        "Successful steps: 198-209 / 2016 (9.82%-10.37%). "
        "Economic score and survival are distinct. No significance or monotonicity claim.",
        fontsize=9,
    )
    save(fig, "l2rpn")


def main() -> None:
    manifest, evidence = load_manifest()
    destination = BASE / "evidence/normalized-v2.json"
    if destination.exists() and json.loads(destination.read_text()) != manifest:
        raise ValueError("Frozen normalized-v2 changed; create a new version instead.")
    ASSETS.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    plot_overview(manifest["cases"])
    plot_repeats(manifest["cases"])
    plot_l2rpn(evidence)
    print(
        json.dumps(
            {
                "cases": len(manifest["cases"]),
                "l2rpn_grades": 15,
                "l2rpn_workflows_completed": 14,
                "figures": 3,
                "l2rpn_normalized_groups": manifest["cases"][-1]["groups"],
            }
        )
    )


if __name__ == "__main__":
    main()
