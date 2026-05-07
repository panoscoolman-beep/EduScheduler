"""Tests για το backend.services.distribution_helper."""
from __future__ import annotations

import pytest

from backend.services.distribution_helper import common_distributions, label


# ---------------------------------------------------------------------------
# common_distributions — coverage σε σύνηθεις τιμές ppw
# ---------------------------------------------------------------------------

def test_invalid_ppw_returns_empty():
    assert common_distributions(0) == []
    assert common_distributions(-1) == []


def test_ppw_1_only_one_split():
    """1 ώρα → μόνο ένα block."""
    out = common_distributions(1, max_block=8)
    assert out == [[1]]


def test_ppw_2_offers_one_double_and_two_singles():
    out = common_distributions(2, max_block=8)
    canons = {tuple(d) for d in out}
    assert (2,) in canons         # 1×2
    assert (1, 1) in canons       # 2×1


def test_ppw_4_includes_equal_splits():
    out = common_distributions(4, max_block=8)
    canons = {tuple(d) for d in out}
    # Must include: 4, 2+2, 1+1+1+1
    assert (4,) in canons
    assert (2, 2) in canons
    assert (1, 1, 1, 1) in canons


def test_ppw_6_includes_classic_3x2_and_2x3():
    """User example: 6 ώρες → 6×1, 3×2, 2×3, 1×6."""
    out = common_distributions(6, max_block=8)
    canons = {tuple(d) for d in out}
    assert (6,) in canons
    assert (3, 3) in canons
    assert (2, 2, 2) in canons
    assert (1, 1, 1, 1, 1, 1) in canons


def test_ppw_5_includes_mixed_options():
    """5 = odd; we expect 5×1, 2+2+1, 3+2, 2+1+1+1, 5"""
    out = common_distributions(5, max_block=8)
    canons = {tuple(d) for d in out}
    assert (5,) in canons
    assert (2, 2, 1) in canons
    assert (3, 2) in canons
    assert (1, 1, 1, 1, 1) in canons


# ---------------------------------------------------------------------------
# max_block constraint
# ---------------------------------------------------------------------------

def test_max_block_filters_out_too_large():
    """Aν max_block=3 και ppw=6, δεν πρέπει να βγει [6] ή [4,2]."""
    out = common_distributions(6, max_block=3)
    canons = {tuple(d) for d in out}
    assert (6,) not in canons
    # Allowed: 3+3, 2+2+2, 3+2+1, 1+1+1+1+1+1
    assert (3, 3) in canons
    assert (2, 2, 2) in canons
    # Πρέπει να μην έχει block > 3
    for d in out:
        assert max(d) <= 3


def test_max_block_smaller_than_ppw_excludes_single_block():
    """ppw=5, max_block=2 → δεν χωράει [5] ή [3,2]."""
    out = common_distributions(5, max_block=2)
    canons = {tuple(d) for d in out}
    assert (5,) not in canons
    assert (3, 2) not in canons
    # Allowed: 2+2+1, 1+1+1+1+1
    assert (2, 2, 1) in canons


def test_max_block_one_only_singles():
    """max_block=1 → μόνο 1×N split."""
    out = common_distributions(6, max_block=1)
    assert len(out) == 1
    assert out[0] == [1, 1, 1, 1, 1, 1]


# ---------------------------------------------------------------------------
# Output invariants
# ---------------------------------------------------------------------------

def test_every_split_sums_to_ppw():
    for ppw in range(1, 11):
        for d in common_distributions(ppw, max_block=8):
            assert sum(d) == ppw, f"split {d} doesn't sum to {ppw}"


def test_no_duplicates_in_output():
    for ppw in (4, 5, 6, 7, 8, 9, 10):
        out = common_distributions(ppw, max_block=8)
        canons = [tuple(d) for d in out]
        assert len(canons) == len(set(canons)), \
            f"duplicates found in ppw={ppw}: {canons}"


def test_blocks_are_descending():
    """Each split is canonical-sorted (descending)."""
    for ppw in range(1, 11):
        for d in common_distributions(ppw, max_block=8):
            assert d == sorted(d, reverse=True), \
                f"split not sorted: {d}"


def test_no_zero_or_negative_blocks():
    for ppw in range(1, 11):
        for d in common_distributions(ppw, max_block=8):
            assert all(b >= 1 for b in d), f"non-positive in {d}"


# ---------------------------------------------------------------------------
# label()
# ---------------------------------------------------------------------------

def test_label_uniform_split():
    assert label([1, 1, 1]) == "3×1ωρα"
    assert label([2, 2]) == "2×2ωρα"
    assert label([3, 3, 3]) == "3×3ωρα"


def test_label_single_block():
    """A single block of N hours reads '1×Nωρα' for unambiguous UI."""
    assert label([6]) == "1×6ωρα"
    assert label([1]) == "1×1ωρα"


def test_label_mixed_split():
    """Mixed splits show grouped counts."""
    out = label([3, 2, 1])
    assert "3" in out
    assert "2" in out
    assert "1" in out


def test_label_handles_empty():
    assert label([]) == "—"
