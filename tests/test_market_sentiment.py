from stock_daily_research.market_sentiment import (
    _change_pct,
    _ratio_change_pct,
    _score_vix,
    sentiment_label,
)


def test_sentiment_label_buckets_scores() -> None:
    assert sentiment_label(10) == "Extreme Fear"
    assert sentiment_label(35) == "Fear"
    assert sentiment_label(50) == "Neutral"
    assert sentiment_label(65) == "Greed"
    assert sentiment_label(90) == "Extreme Greed"


def test_sentiment_component_helpers_score_market_inputs() -> None:
    assert _change_pct([100] * 20 + [110], 20) == 10.0
    assert abs(_ratio_change_pct([100] * 20 + [110], [100] * 21, 20) - 10.0) < 0.001
    assert _score_vix(10) == 90.0
    assert _score_vix(40) == 10.0
    assert 40 < _score_vix(22) < 70
