from stock_daily_research.market_context import rates_interpretation
from stock_daily_research.models import RateLevel


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
