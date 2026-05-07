"""Helper για το UI-friendly distribution selector.

Δίνει στον frontend μια λίστα από common/useful block splits για κάθε
periods_per_week + max_block_size. Π.χ. για 6 ώρες/εβδομάδα και 7
διδακτικές ώρες/μέρα:

    [[1,1,1,1,1,1], [2,2,2], [3,3], [6], [2,1,1,1,1], [3,2,1], ...]

Sorted by elegance: pure equal-splits first, then mixed.
"""
from __future__ import annotations


def common_distributions(ppw: int, max_block: int = 8) -> list[list[int]]:
    """Όλα τα ωραία splits του `ppw` σε blocks ≤ max_block.

    Επιστρέφει uniqued, sorted-by-niceness λίστα. Κάθε εσωτερική
    λίστα είναι sorted descending για canonical comparison.
    """
    if ppw < 1:
        return []
    if max_block < 1:
        max_block = 1

    candidates: list[tuple[int, list[int]]] = []  # (priority, blocks)

    # 1. All ones — most common default, listed first
    candidates.append((0, [1] * ppw))

    # 2. Single block — only if fits in a day; useful but unusual
    if ppw <= max_block:
        candidates.append((6, [ppw]))

    # 3. Equal splits (N×size, where size ≤ max_block, ppw%size==0)
    for size in range(2, min(max_block, ppw) + 1):
        if ppw % size == 0:
            candidates.append((2, [size] * (ppw // size)))

    # 4. "One double + rest 1s" pattern για odd ppw ≥ 3
    if ppw >= 3 and 2 <= max_block:
        # Two blocks of 2, rest 1s — useful for ppw=5, 7, 9
        if ppw - 2 >= 1:
            candidates.append((3, [2] + [1] * (ppw - 2)))

    # 5. "Mostly doubles + one single" για odd ppw ≥ 5
    if ppw >= 5 and ppw % 2 == 1 and max_block >= 2:
        candidates.append((3, [2] * ((ppw - 1) // 2) + [1]))

    # 6. Mixed largest+rest για 4-8 ώρες
    if ppw >= 4:
        # 1 block of size 3 + rest as 2s or 1s
        if ppw - 3 >= 0 and max_block >= 3:
            rem = ppw - 3
            if rem == 0:
                pass  # already in single-block
            elif rem == 1:
                candidates.append((4, [3, 1]))
            elif rem == 2:
                candidates.append((4, [3, 2]))
            elif rem >= 2 and rem % 2 == 0:
                candidates.append((4, [3] + [2] * (rem // 2)))

    # 7. 4+rest pattern για 5-8 ώρες
    if ppw >= 5 and max_block >= 4:
        rem = ppw - 4
        if rem == 1:
            candidates.append((5, [4, 1]))
        elif rem == 2:
            candidates.append((5, [4, 2]))
        elif rem == 3:
            candidates.append((5, [4, 3]))

    # Dedup (canonical = sorted descending) and stable-sort by priority.
    seen: set[tuple[int, ...]] = set()
    out: list[list[int]] = []
    for prio, blocks in sorted(candidates, key=lambda x: x[0]):
        canon = tuple(sorted(blocks, reverse=True))
        if canon in seen:
            continue
        # Filter out anything that contains a block bigger than max_block
        if max(canon) > max_block:
            continue
        # Filter sanity check: must sum to ppw
        if sum(canon) != ppw:
            continue
        seen.add(canon)
        out.append(list(canon))

    return out


def label(blocks: list[int]) -> str:
    """Pretty label like '6×1ωρα' or '2×3 + 1×2'."""
    if not blocks:
        return "—"
    if len(set(blocks)) == 1:
        size = blocks[0]
        if size == 1:
            return f"{len(blocks)}×1ωρα"
        return f"{len(blocks)}×{size}ωρα"
    # Mixed — group by size
    counts: dict[int, int] = {}
    for b in blocks:
        counts[b] = counts.get(b, 0) + 1
    parts = []
    for size in sorted(counts.keys(), reverse=True):
        cnt = counts[size]
        suffix = "ωρα" if size > 1 else "ωρα"
        parts.append(f"{cnt}×{size}{suffix}" if cnt > 1 else f"{size}{suffix}")
    return " + ".join(parts)
