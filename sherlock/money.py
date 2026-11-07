"""Integer-cent arithmetic helpers. No floats touch money."""

from __future__ import annotations


def split_cents(total: int, weights: list[int]) -> list[int]:
    """Split `total` across `weights` proportionally, in integer cents, summing exactly to `total`.
    Largest-remainder method. Zero/empty weights split evenly."""
    n = len(weights)
    if n == 0:
        return []
    if sum(weights) <= 0:
        weights = [1] * n
    wsum = sum(weights)
    base = [total * w // wsum for w in weights]
    remainder = total - sum(base)
    # Hand out leftover cents to the largest fractional parts, ties by index for determinism.
    fracs = sorted(range(n), key=lambda i: ((total * weights[i]) % wsum, -i), reverse=True)
    for i in fracs[:remainder]:
        base[i] += 1
    return base


def pct_diff(a: int, b: int) -> float:
    """Absolute percentage difference of a vs b, relative to the larger magnitude. Not money."""
    big = max(abs(a), abs(b))
    return 0.0 if big == 0 else abs(a - b) * 100.0 / big


def fmt_usd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
