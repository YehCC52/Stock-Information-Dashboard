from pathlib import Path

from stock_daily_research.models import TickerConfig, TrustedXAccount
from stock_daily_research.x_signals import load_manual_x_signals


def test_manual_x_signals_filters_untrusted_accounts(tmp_path: Path) -> None:
    path = tmp_path / "x_posts.yaml"
    path.write_text(
        """
posts:
  - ticker: NVDA
    author_handle: trusted
    author_category: industry_expert
    text: Trusted post
    url: https://x.com/trusted/status/1
  - ticker: NVDA
    author_handle: random
    author_category: industry_expert
    text: Random post
    url: https://x.com/random/status/2
""",
        encoding="utf-8",
    )
    tickers = [
        TickerConfig(
            symbol="NVDA",
            company_name="NVIDIA Corporation",
            trusted_x_accounts=[TrustedXAccount(handle="trusted", category="industry_expert")],
        )
    ]

    signals = load_manual_x_signals(path, tickers)

    assert len(signals) == 1
    assert signals[0].author_handle == "trusted"
