#!/usr/bin/env python3
"""Generate reproducible, poster-ready exploratory figures and summary statistics."""
11
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
matplotlib_cache = Path(tempfile.gettempdir()) / "homelens-matplotlib"
matplotlib_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_cache))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.utils import write_json  # noqa: E402


INK = "#183238"
MUTED = "#65777b"
TEAL = "#0b776f"
TEAL_LIGHT = "#cfe7e2"
CORAL = "#e26a4f"
GOLD = "#d5a432"
GRID = "#dde1de"
BACKGROUND = "#fbfaf6"
PALETTE = [TEAL, CORAL, GOLD, "#718c75", "#c77ca3", "#526f78", "#9b7459"]


def style_axes(axis: plt.Axes) -> None:
    axis.set_facecolor(BACKGROUND)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=9)
    axis.grid(axis="y", color=GRID, linewidth=0.7, alpha=0.8)
    axis.set_axisbelow(True)


def title_figure(figure: plt.Figure, title: str, subtitle: str) -> None:
    figure.suptitle(title, x=0.08, y=0.965, ha="left", color=INK, fontsize=17, fontweight="bold")
    figure.text(0.08, 0.915, subtitle, ha="left", color=MUTED, fontsize=9)


def source_note(figure: plt.Figure, text: str) -> None:
    figure.text(0.08, 0.025, text, ha="left", color=MUTED, fontsize=7.5)


def save(figure: plt.Figure, path: Path) -> None:
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor=BACKGROUND)
    plt.close(figure)


def monthly_price_trend(transactions: pd.DataFrame, output: Path) -> dict:
    focus = ["3 ROOM", "4 ROOM", "5 ROOM"]
    monthly = (
        transactions.loc[transactions["flat_type"].isin(focus)]
        .groupby(["month", "flat_type"], as_index=False)
        .agg(median_price=("resale_price", "median"), transactions=("resale_price", "size"))
    )
    figure, axis = plt.subplots(figsize=(10.8, 5.8))
    style_axes(axis)
    for flat_type, color in zip(focus, PALETTE):
        series = monthly.loc[monthly["flat_type"] == flat_type]
        axis.plot(
            series["month"],
            series["median_price"] / 1_000,
            label=flat_type.title(),
            color=color,
            linewidth=2.1,
        )
    axis.set_ylabel("Median resale price (S$ thousands)", color=MUTED, fontsize=9)
    axis.set_xlabel("")
    axis.legend(frameon=False, ncol=3, loc="upper left", fontsize=9)
    title_figure(
        figure,
        "Monthly median HDB resale price by flat type",
        f"Complete observed months · {monthly['month'].min():%b %Y} to {monthly['month'].max():%b %Y}",
    )
    source_note(figure, "Source: data.gov.sg HDB resale transactions. Prices are nominal and unadjusted for inflation.")
    figure.tight_layout(rect=(0.04, 0.06, 0.98, 0.88))
    save(figure, output)
    return {"temporal_points": int(monthly["month"].nunique()), "series": focus}


def town_price_per_sqm(recent: pd.DataFrame, output: Path) -> dict:
    towns = (
        recent.loc[recent["flat_type"] == "4 ROOM"]
        .groupby("town", as_index=False)
        .agg(
            median_price_per_sqm=("price_per_sqm", "median"),
            transactions=("resale_price", "size"),
        )
    )
    towns = towns.loc[towns["transactions"] >= 30].nlargest(15, "median_price_per_sqm")
    towns = towns.sort_values("median_price_per_sqm")
    figure, axis = plt.subplots(figsize=(10.8, 6.2))
    style_axes(axis)
    bars = axis.barh(
        towns["town"].str.title(), towns["median_price_per_sqm"], color=TEAL, edgecolor=INK, linewidth=0.35
    )
    axis.grid(axis="x", color=GRID, linewidth=0.7)
    axis.grid(axis="y", visible=False)
    axis.set_xlabel("Median price per sqm (S$)", color=MUTED, fontsize=9)
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
    for bar, count in zip(bars, towns["transactions"]):
        axis.text(
            bar.get_width() + towns["median_price_per_sqm"].max() * 0.012,
            bar.get_y() + bar.get_height() / 2,
            f"n={int(count):,}",
            va="center",
            color=MUTED,
            fontsize=7.5,
        )
    axis.set_xlim(0, towns["median_price_per_sqm"].max() * 1.17)
    title_figure(
        figure,
        "Four-room resale price per sqm by town",
        f"Top 15 towns · median of transactions from {recent['month'].min():%b %Y} to {recent['month'].max():%b %Y} · minimum n=30",
    )
    source_note(figure, "Source: data.gov.sg HDB resale transactions. Town mix and flat attributes are not controlled in this descriptive view.")
    figure.tight_layout(rect=(0.04, 0.06, 0.98, 0.88))
    save(figure, output)
    return {
        "towns": int(len(towns)),
        "highest_town": str(towns.iloc[-1]["town"]),
        "highest_median_price_per_sqm": float(towns.iloc[-1]["median_price_per_sqm"]),
    }


def price_distribution(recent: pd.DataFrame, output: Path) -> dict:
    order = [
        flat_type
        for flat_type in [
            "2 ROOM",
            "3 ROOM",
            "4 ROOM",
            "5 ROOM",
            "EXECUTIVE",
            "MULTI-GENERATION",
        ]
        if flat_type in set(recent["flat_type"])
    ]
    values = [recent.loc[recent["flat_type"] == flat_type, "resale_price"] / 1_000 for flat_type in order]
    counts = [int((recent["flat_type"] == flat_type).sum()) for flat_type in order]
    figure, axis = plt.subplots(figsize=(10.8, 5.9))
    style_axes(axis)
    box = axis.boxplot(
        values,
        vert=False,
        patch_artist=True,
        showfliers=False,
        widths=0.55,
        medianprops={"color": INK, "linewidth": 1.5},
        whiskerprops={"color": MUTED},
        capprops={"color": MUTED},
    )
    axis.set_yticks(
        range(1, len(order) + 1),
        labels=[f"{label.title()} (n={count:,})" for label, count in zip(order, counts)],
    )
    teal_shades = ["#cfe7e2", "#acd4cd", "#7bbab1", "#44988f", TEAL, INK]
    for patch, color in zip(box["boxes"], teal_shades):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
        patch.set_edgecolor(INK)
        patch.set_linewidth(0.5)
    axis.grid(axis="x", color=GRID, linewidth=0.7)
    axis.grid(axis="y", visible=False)
    axis.set_xlabel("Resale price (S$ thousands)", color=MUTED, fontsize=9)
    title_figure(
        figure,
        "Recent resale-price distribution by flat type",
        f"Middle 50%, median and non-outlier range · {recent['month'].min():%b %Y} to {recent['month'].max():%b %Y} · outlier points hidden",
    )
    source_note(figure, f"Source: data.gov.sg HDB resale transactions. Total observations shown in distribution: n={len(recent):,}.")
    figure.tight_layout(rect=(0.04, 0.06, 0.98, 0.88))
    save(figure, output)
    return {"observations": int(len(recent)), "flat_types": order}


def candidate_tradeoffs(candidates: pd.DataFrame, output: Path) -> dict:
    plot = candidates.dropna(
        subset=["median_resale_price", "median_floor_area_sqm", "median_remaining_lease_years"]
    ).copy()
    sizes = 12 + np.sqrt(plot["recent_transaction_count"].clip(lower=1)) * 5
    lease_cmap = LinearSegmentedColormap.from_list("lease", [TEAL_LIGHT, TEAL, INK])
    figure, axis = plt.subplots(figsize=(10.8, 6.2))
    style_axes(axis)
    scatter = axis.scatter(
        plot["median_resale_price"] / 1_000,
        plot["median_floor_area_sqm"],
        c=plot["median_remaining_lease_years"],
        s=sizes,
        cmap=lease_cmap,
        alpha=0.55,
        linewidths=0,
    )
    axis.grid(axis="both", color=GRID, linewidth=0.7)
    axis.set_xlabel("Candidate median resale price (S$ thousands)", color=MUTED, fontsize=9)
    axis.set_ylabel("Candidate median floor area (sqm)", color=MUTED, fontsize=9)
    colorbar = figure.colorbar(scatter, ax=axis, pad=0.02)
    colorbar.set_label("Median remaining lease (years)", color=MUTED, fontsize=9)
    colorbar.ax.tick_params(labelsize=8, colors=MUTED)
    title_figure(
        figure,
        "Price, space and remaining-lease trade-offs",
        f"One point per block + flat-type candidate · n={len(plot):,}; marker size reflects recent transaction count",
    )
    source_note(figure, "Source: HomeLens candidate knowledge base built from the latest 24 months of data.gov.sg HDB transactions.")
    figure.tight_layout(rect=(0.04, 0.06, 0.98, 0.88))
    save(figure, output)
    return {"candidate_points": int(len(plot)), "grain": "block + flat type"}


def model_comparison(metrics_path: Path, output: Path) -> dict:
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    names = ["MAE", "RMSE"]
    baseline = [metrics["baseline"]["mae"], metrics["baseline"]["rmse"]]
    forest = [metrics["random_forest"]["mae"], metrics["random_forest"]["rmse"]]
    x = np.arange(len(names))
    width = 0.34
    figure, axis = plt.subplots(figsize=(8.8, 5.6))
    style_axes(axis)
    baseline_bars = axis.bar(x - width / 2, baseline, width, label="Historical median baseline", color=TEAL_LIGHT, edgecolor=TEAL)
    forest_bars = axis.bar(x + width / 2, forest, width, label="Random forest", color=CORAL, edgecolor=INK, linewidth=0.4)
    axis.set_xticks(x, names)
    axis.set_ylabel("Error (S$)", color=MUTED, fontsize=9)
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value/1_000:,.0f}k"))
    axis.legend(frameon=False, loc="upper right", fontsize=8.5)
    for bars in (baseline_bars, forest_bars):
        axis.bar_label(bars, labels=[f"${value/1_000:,.1f}k" for value in bars.datavalues], padding=4, fontsize=8, color=INK)
    axis.set_ylim(0, max(baseline) * 1.22)
    title_figure(
        figure,
        "Chronological holdout error by model",
        f"Train through {metrics['training_end_month'][:7]}; test {metrics['test_start_month'][:7]} to {metrics['test_end_month'][:7]} · test n={metrics['test_rows']:,}",
    )
    source_note(figure, f"Random-forest MAPE: {metrics['random_forest']['mape_percent']:.2f}%. The holdout is time-based, not random.")
    figure.tight_layout(rect=(0.04, 0.06, 0.98, 0.88))
    save(figure, output)
    return {
        "baseline_mae": baseline[0],
        "random_forest_mae": forest[0],
        "mae_improvement_percent": metrics["mae_improvement_over_baseline_percent"],
    }


def main() -> None:
    clean_path = PROJECT_ROOT / "data" / "processed" / "hdb_transactions_clean.csv"
    candidates_path = PROJECT_ROOT / "data" / "processed" / "hdb_candidates.csv"
    metrics_path = PROJECT_ROOT / "artifacts" / "metrics" / "price_model.json"
    missing = [path for path in (clean_path, candidates_path, metrics_path) if not path.exists()]
    if missing:
        raise SystemExit("Missing pipeline output(s): " + ", ".join(str(path) for path in missing))

    output_dir = PROJECT_ROOT / "artifacts" / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)
    transactions = pd.read_csv(clean_path, parse_dates=["month"], low_memory=False)
    candidates = pd.read_csv(candidates_path, low_memory=False)
    source_maximum_month = transactions["month"].max()
    latest_month_is_partial = (
        source_maximum_month.to_period("M") == pd.Timestamp.now().to_period("M")
    )
    analysis_maximum_month = (
        source_maximum_month - pd.DateOffset(months=1)
        if latest_month_is_partial
        else source_maximum_month
    )
    analysis_transactions = transactions.loc[
        transactions["month"] <= analysis_maximum_month
    ].copy()
    recent_cutoff = analysis_maximum_month - pd.DateOffset(months=23)
    recent = analysis_transactions.loc[
        analysis_transactions["month"] >= recent_cutoff
    ].copy()

    chart_outputs = {
        "monthly_price_trend": monthly_price_trend(
            analysis_transactions, output_dir / "01_monthly_price_trend.png"
        ),
        "town_price_per_sqm": town_price_per_sqm(
            recent, output_dir / "02_town_price_per_sqm.png"
        ),
        "price_distribution": price_distribution(
            recent, output_dir / "03_price_distribution.png"
        ),
        "candidate_tradeoffs": candidate_tradeoffs(
            candidates, output_dir / "04_candidate_tradeoffs.png"
        ),
        "model_comparison": model_comparison(
            metrics_path, output_dir / "05_model_comparison.png"
        ),
    }

    latest_complete_month = analysis_maximum_month
    current_start = latest_complete_month - pd.DateOffset(months=11)
    previous_start = current_start - pd.DateOffset(months=12)
    current = transactions.loc[
        transactions["month"].between(current_start, latest_complete_month)
    ]
    previous = transactions.loc[
        transactions["month"].between(previous_start, current_start - pd.DateOffset(months=1))
    ]
    current_medians = current.groupby("flat_type")["resale_price"].median()
    previous_medians = previous.groupby("flat_type")["resale_price"].median()
    comparable = current_medians.index.intersection(previous_medians.index)
    change = ((current_medians[comparable] / previous_medians[comparable]) - 1) * 100
    summary = {
        "source": "data.gov.sg HDB resale transactions",
        "transaction_rows": int(len(transactions)),
        "analysis_transaction_rows": int(len(analysis_transactions)),
        "candidate_rows": int(len(candidates)),
        "minimum_month": transactions["month"].min(),
        "maximum_month": source_maximum_month,
        "analysis_maximum_month": analysis_maximum_month,
        "latest_month_is_partial": latest_month_is_partial,
        "partial_month_rows_excluded_from_analysis": int(
            len(transactions) - len(analysis_transactions)
        ),
        "recent_window_start": recent_cutoff,
        "recent_window_rows": int(len(recent)),
        "latest_complete_12m_start": current_start,
        "latest_complete_12m_end": latest_complete_month,
        "median_price_change_vs_previous_12m_percent": {
            flat_type: float(change[flat_type]) for flat_type in comparable
        },
        "charts": chart_outputs,
    }
    write_json(PROJECT_ROOT / "artifacts" / "metrics" / "eda_summary.json", summary)
    chart_map = {
        "01_monthly_price_trend.png": {
            "question": "How have typical prices moved over time for common flat types?",
            "family": "trend / highlighted multi-series line",
            "takeaway_scope": "shape and divergence over 115+ monthly observations",
        },
        "02_town_price_per_sqm.png": {
            "question": "Which towns have the highest recent four-room price per sqm?",
            "family": "comparison / ranked horizontal bar",
            "takeaway_scope": "descriptive town comparison with transaction counts",
        },
        "03_price_distribution.png": {
            "question": "How do recent price levels and spreads differ by flat type?",
            "family": "distribution / horizontal box plot",
            "takeaway_scope": "median and interquartile spread; outlier points hidden",
        },
        "04_candidate_tradeoffs.png": {
            "question": "What price, space and lease trade-offs exist among candidates?",
            "family": "relationship / scatter",
            "takeaway_scope": "block + flat-type grain with volume context",
        },
        "05_model_comparison.png": {
            "question": "Does the learned model improve on the historical-median baseline?",
            "family": "comparison / grouped bar",
            "takeaway_scope": "MAE and RMSE on a chronological holdout",
        },
    }
    write_json(PROJECT_ROOT / "artifacts" / "manifests" / "chart_map.json", chart_map)
    print(json.dumps({"output_dir": str(output_dir), **summary}, indent=2, default=str))


if __name__ == "__main__":
    main()
