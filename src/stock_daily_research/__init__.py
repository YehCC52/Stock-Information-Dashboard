"""Daily stock research report toolkit."""

__all__ = ["__version__", "run_daily"]

__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "run_daily":
        from .runner import run_daily

        return run_daily
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
