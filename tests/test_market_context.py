from datetime import datetime, timezone

from stock_daily_research.market_context import market_regime, rates_interpretation
from stock_daily_research.models import MarketContext, MarketSentiment, RateLevel


def test_rates_interpretation_yields_rising() -> None:
    rates = [
        RateLevel(name="5Y", last=4.5, prev=4.4, change=10.0, unit="bp"),
        RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
        RateLevel(name="DXY", last=104.5, prev=104.0, change=0.48, unit="%"),
    ]
    msg = rates_interpretation(rates)
    assert "Yields rising" in msg
    assert "headwind" in msg
    assert "DXY" in msg
    assert "risk-off" in msg


def test_rates_interpretation_yields_falling() -> None:
    rates = [
        RateLevel(name="5Y", last=4.4, prev=4.5, change=-10.0, unit="bp"),
        RateLevel(name="10Y", last=4.6, prev=4.7, change=-8.0, unit="bp"),
    ]
    msg = rates_interpretation(rates)
    assert "Yields falling" in msg
    assert "tailwind" in msg


def test_rates_interpretation_mixed() -> None:
    rates = [
        RateLevel(name="5Y", last=4.5, prev=4.5, change=0.0, unit="bp"),
        RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
    ]
    msg = rates_interpretation(rates)
    assert "mixed" in msg.lower()


def test_rates_interpretation_empty() -> None:
    assert rates_interpretation([]) == ""


def test_rates_interpretation_inflation_pressure() -> None:
    """Yields + WTI both up → inflation pressure framing."""
    rates = [
        RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
        RateLevel(name="5Y", last=4.5, prev=4.4, change=6.0, unit="bp"),
        RateLevel(name="WTI", last=82.50, prev=80.10, change=3.00, unit="%"),
    ]
    msg = rates_interpretation(rates)
    assert "Inflation pressure" in msg


def test_rates_interpretation_macro_tailwind() -> None:
    """Yields + WTI both down → macro tailwind."""
    rates = [
        RateLevel(name="10Y", last=4.4, prev=4.5, change=-10.0, unit="bp"),
        RateLevel(name="5Y", last=4.3, prev=4.4, change=-8.0, unit="bp"),
        RateLevel(name="WTI", last=77.50, prev=80.00, change=-3.13, unit="%"),
    ]
    msg = rates_interpretation(rates)
    assert "Macro tailwind" in msg


def test_rates_interpretation_oil_firm_only() -> None:
    """No clear yield direction but WTI up → oil-only framing."""
    rates = [
        RateLevel(name="10Y", last=4.5, prev=4.5, change=0.0, unit="bp"),
        RateLevel(name="WTI", last=82.0, prev=80.0, change=2.5, unit="%"),
    ]
    msg = rates_interpretation(rates)
    assert "Oil firm" in msg


def _ctx(rates: list[RateLevel]) -> MarketContext:
    return MarketContext(
        rates=rates,
        retrieved_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
    )


def test_market_regime_oil_led_inflation() -> None:
    ctx = _ctx([
        RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
        RateLevel(name="WTI", last=82.0, prev=80.0, change=2.5, unit="%"),
    ])
    assert market_regime(ctx, sentiment_score=55) == "Oil-led inflation pressure"


def test_market_regime_risk_on_easing_rates() -> None:
    ctx = _ctx([
        RateLevel(name="10Y", last=4.4, prev=4.5, change=-8.0, unit="bp"),
        RateLevel(name="5Y", last=4.3, prev=4.4, change=-6.0, unit="bp"),
        RateLevel(name="WTI", last=77.0, prev=80.0, change=-3.75, unit="%"),
    ])
    assert market_regime(ctx, sentiment_score=72) == "Risk-on with easing rates"


def test_market_regime_defensive_when_yields_up_and_low_sentiment() -> None:
    ctx = _ctx([
        RateLevel(name="10Y", last=4.7, prev=4.6, change=8.0, unit="bp"),
    ])
    assert market_regime(ctx, sentiment_score=35) == "Defensive: yields up, sentiment cautious"


def test_market_regime_returns_empty_without_data() -> None:
    assert market_regime(None, sentiment_score=50) == ""
    assert market_regime(_ctx([]), sentiment_score=50) == ""


def test_n_day_return_from_closes_supports_long_market_horizons() -> None:
    from stock_daily_research.market_context import _n_day_return_from_closes

    closes = [float(value) for value in range(1, 122)]

    assert _n_day_return_from_closes(closes, 120) == 12000.0
    assert _n_day_return_from_closes(closes, 121) is None