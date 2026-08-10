from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import BacktestMarketResult, BacktestResult


def backtest_output_dir(
    base_dir: str | Path,
    generated_at: datetime,
) -> Path:
    return (
        Path(base_dir)
        / "backtests"
        / f"{generated_at.year:04d}"
        / f"{generated_at.month:02d}"
    )


def backtest_payload(result: BacktestResult) -> dict[str, Any]:
    return asdict(result)


def backtest_summary_payload(result: BacktestResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "strategy": result.strategy,
        "rule_version": result.rule_version,
        "requested_start": result.requested_start,
        "requested_end": result.requested_end,
        "deterministic_replay_passed": result.deterministic_replay_passed,
        "universe_source": result.universe_source,
        "universe": [asdict(member) for member in result.universe],
        "markets": [
            {
                "market": market.market,
                "currency": market.currency,
                "metrics": market.metrics,
                "in_sample_metrics": market.in_sample_metrics,
                "out_of_sample_metrics": market.out_of_sample_metrics,
                "diagnostics": market.diagnostics,
                "robustness": market.robustness,
            }
            for market in result.markets
        ],
        "warnings": result.warnings,
    }


def render_backtest_html(
    result: BacktestResult,
    template_dir: str | Path | None = None,
) -> str:
    env = _environment(template_dir, html=True)
    return env.get_template("backtest_report.html.j2").render(
        result=result,
        market_views=[_market_view(market) for market in result.markets],
        generated_label=result.generated_at.astimezone().strftime(
            "%Y-%m-%d %H:%M %Z"
        ),
    )


def render_backtest_markdown(
    result: BacktestResult,
    template_dir: str | Path | None = None,
) -> str:
    env = _environment(template_dir, html=False)
    return env.get_template("backtest_report.md.j2").render(
        result=result,
        market_views=[_market_view(market) for market in result.markets],
    )


def write_backtest_report(
    result: BacktestResult,
    output_dir: str | Path,
    *,
    template_dir: str | Path | None = None,
) -> dict[str, Path]:
    target_dir = backtest_output_dir(output_dir, result.generated_at)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"right-side_{result.requested_start.isoformat()}_"
        f"{result.requested_end.isoformat()}_{result.run_id[-8:]}"
    )
    paths = {
        "html": target_dir / f"{stem}.html",
        "markdown": target_dir / f"{stem}.md",
        "json": target_dir / f"{stem}.json",
    }
    paths["html"].write_text(
        render_backtest_html(result, template_dir),
        encoding="utf-8",
    )
    paths["markdown"].write_text(
        render_backtest_markdown(result, template_dir),
        encoding="utf-8",
    )
    paths["json"].write_text(
        json.dumps(
            backtest_payload(result),
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def _environment(
    template_dir: str | Path | None,
    *,
    html: bool,
) -> Environment:
    path = (
        Path(template_dir)
        if template_dir
        else Path(__file__).parent / "templates"
    )
    return Environment(
        loader=FileSystemLoader(path),
        autoescape=select_autoescape(["html", "xml"]) if html else False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _market_view(market: BacktestMarketResult) -> dict[str, Any]:
    return {
        "result": market,
        "chart": _chart_points(market),
        "trade_rows": [_trade_view(trade) for trade in market.trades],
        "robustness": _robustness_view(market),
        "setup_counts": _translated_counts(
            market.diagnostics.get("setup_counts", {}),
            {
                "breakout": "突破進場",
                "pullback": "回檔承接",
            },
        ),
        "signal_rejections": _translated_counts(
            market.diagnostics.get("signal_rejections", {}),
            {
                "insufficient_history": "歷史資料不足",
                "no_actionable_structure": "尚無可執行結構",
                "missing_risk_level": "缺少停損依據",
                "signal_risk_too_wide": "訊號風險過大",
                "relative_strength": "相對強度不足",
                "duplicate_signal_streak": "重複訊號冷卻中",
            },
        ),
        "simulation_rejections": _translated_counts(
            market.diagnostics.get("simulation_rejections", {}),
            {
                "position_limit": "部位數已滿",
                "already_open": "已持有該標的",
                "missing_entry_bar": "缺少進場日資料",
                "entry_gap_too_high": "跳空幅度過大",
                "opened_below_stop": "開盤跌破停損",
                "fill_risk_too_wide": "成交後風險過大",
                "insufficient_cash_or_risk": "現金或風險額度不足",
                "unclosed_missing_bar": "缺少平倉資料",
                "locked_limit_entry": "漲跌停鎖死，無法進場",
                "no_entry_liquidity": "成交量不足",
            },
        ),
        "execution_adjustments": _translated_counts(
            market.diagnostics.get("execution_adjustments", {}),
            {
                "volume_capped_entries": "依成交量縮減部位",
                "locked_limit_exit_deferred": "跌停鎖死，延後出場",
            },
        ),
        "exit_counts": _translated_counts(
            _count_by(market.trades, "exit_reason"),
            {
                "target": "達到 2R 目標",
                "stop": "觸及停損",
                "gap_stop": "跳空停損",
                "stop_first_ambiguous": "同日觸價，保守停損",
                "time_exit": "持有期到期",
                "period_end": "回測期結束",
            },
        ),
    }


_STATUS_LABELS = {
    "stable": "穩定",
    "mixed": "結果分歧",
    "fragile": "穩健度偏弱",
    "insufficient": "樣本不足",
    "disabled": "未啟用",
    "sensitive": "參數敏感",
    "diversified": "獲利分散",
    "concentrated": "獲利集中",
    "ok": "正常",
    "warning": "需留意",
    "unavailable": "無資料",
}

_STATUS_TONES = {
    "stable": "positive",
    "diversified": "positive",
    "ok": "positive",
    "fragile": "negative",
    "sensitive": "negative",
    "concentrated": "negative",
    "mixed": "warning",
    "insufficient": "warning",
    "warning": "warning",
    "unavailable": "warning",
    "disabled": "subtle",
}

_QUALITY_REASON_LABELS = {
    "unavailable": "無可用行情",
    "stale": "最後資料日過舊",
    "sparse": "交易日涵蓋率偏低",
    "extreme_returns": "單日價格跳動異常",
    "zero_volume": "零成交量比例偏高",
}


def _robustness_view(market: BacktestMarketResult) -> dict[str, Any]:
    raw = market.robustness
    walk_forward = raw.get("walk_forward", {})
    sensitivity = raw.get("sensitivity", {})
    concentration = raw.get("concentration", {})
    data_quality = market.diagnostics.get("data_quality", {})
    quality_rows: list[dict[str, Any]] = []
    for raw_row in data_quality.get("rows", []):
        row = dict(raw_row)
        status = str(row.get("status", "unavailable"))
        row.update(_status_view(status))
        labels = [
            _QUALITY_REASON_LABELS.get(str(reason), str(reason))
            for reason in row.get("reasons", [])
        ]
        row["reason_label"] = "、".join(labels) or "未發現明顯異常"
        quality_rows.append(row)

    if int(data_quality.get("unavailable_count", 0)):
        quality_status = "unavailable"
    elif int(data_quality.get("warning_count", 0)):
        quality_status = "warning"
    elif quality_rows:
        quality_status = "ok"
    else:
        quality_status = "insufficient"

    return {
        "overall": _status_view(str(raw.get("status", "insufficient"))),
        "walk_forward": {
            "summary": _summary_view(walk_forward.get("summary", {})),
            "rows": walk_forward.get("rows", []),
        },
        "sensitivity": {
            "summary": _summary_view(sensitivity.get("summary", {})),
            "rows": sensitivity.get("rows", []),
        },
        "concentration": _summary_view(concentration),
        "data_quality": {
            **data_quality,
            **_status_view(quality_status),
            "rows": quality_rows,
        },
    }


def _summary_view(payload: object) -> dict[str, Any]:
    row = dict(payload) if isinstance(payload, dict) else {}
    return {
        **row,
        **_status_view(str(row.get("status", "insufficient"))),
    }


def _status_view(status: str) -> dict[str, str]:
    return {
        "status": status,
        "status_label": _STATUS_LABELS.get(status, status),
        "status_tone": _STATUS_TONES.get(status, "subtle"),
    }


def _chart_points(market: BacktestMarketResult) -> dict[str, Any]:
    points = market.equity_curve
    if not points:
        return {
            "strategy": "",
            "benchmark": "",
            "split_x": 0.0,
            "start": "",
            "end": "",
        }
    values = [point.equity for point in points]
    benchmark = [
        point.benchmark_equity
        for point in points
        if point.benchmark_equity is not None
    ]
    scale_values = [*values, *benchmark]
    low = min(scale_values)
    high = max(scale_values)
    span = high - low or 1.0

    def polyline(series: list[float | None]) -> str:
        rendered: list[str] = []
        denominator = max(1, len(series) - 1)
        for index, value in enumerate(series):
            if value is None:
                continue
            x = index / denominator * 100.0
            y = 34.0 - (float(value) - low) / span * 30.0
            rendered.append(f"{x:.2f},{y:.2f}")
        return " ".join(rendered)

    split_index = next(
        (
            index
            for index, point in enumerate(points)
            if point.session_date >= market.split_date
        ),
        len(points) - 1,
    )
    return {
        "strategy": polyline(values),
        "benchmark": polyline(
            [point.benchmark_equity for point in points]
        ),
        "split_x": split_index / max(1, len(points) - 1) * 100.0,
        "start": points[0].session_date.isoformat(),
        "end": points[-1].session_date.isoformat(),
    }


def _count_by(rows: list[Any], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, field))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _trade_view(trade: Any) -> dict[str, Any]:
    row = asdict(trade)
    row["setup_label"] = {
        "breakout": "突破進場",
        "pullback": "回檔承接",
    }.get(trade.setup, trade.setup)
    row["exit_label"] = {
        "target": "達到 2R 目標",
        "stop": "觸及停損",
        "gap_stop": "跳空停損",
        "stop_first_ambiguous": "同日觸價，保守停損",
        "time_exit": "持有期到期",
        "period_end": "回測期結束",
    }.get(trade.exit_reason, trade.exit_reason)
    return row


def _translated_counts(
    counts: object,
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    if not isinstance(counts, dict):
        return []
    return [
        {
            "key": str(key),
            "label": labels.get(str(key), str(key)),
            "count": int(value),
        }
        for key, value in sorted(
            counts.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )
    ]


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")
