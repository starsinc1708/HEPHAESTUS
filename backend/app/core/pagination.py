"""PERF-003: shared offset/limit pagination for accumulating list endpoints.

List endpoints that grow over time (goals, ideas, insights sessions) return the
full dataset in one response. The stores already enforce rolling caps on disk
(see each store's ``_MAX_KEEP``), so responses are bounded — but there is no way
for a client to page or to learn the true ``total``. ``paginate`` adds that:
an opt-in offset/limit window plus a ``{total, offset, limit}`` meta block.

Default behaviour is non-breaking: ``DEFAULT_LIMIT`` is larger than every store
cap, so an un-parameterised call returns the whole (already-capped) list, exactly
as before, just with the extra ``total``/``offset``/``limit`` fields.
"""

from __future__ import annotations

# Larger than every store's rolling cap (goals/insights 200, ideas 500) so the
# default response is unchanged; a client only ever sees fewer items by asking.
DEFAULT_LIMIT = 500
# Hard ceiling so a hostile/typo'd ?limit=999999 can't force a giant slice op.
MAX_LIMIT = 1000


def clamp_offset(offset: int | None) -> int:
    """Negative/None offset -> 0."""
    if offset is None or offset < 0:
        return 0
    return offset


def clamp_limit(limit: int | None) -> int:
    """None/<=0 -> DEFAULT_LIMIT; otherwise capped at MAX_LIMIT."""
    if limit is None or limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def paginate[T](
    items: list[T], offset: int | None = None, limit: int | None = None
) -> tuple[list[T], dict[str, int]]:
    """Return ``(window, meta)`` where ``meta == {total, offset, limit}``.

    ``total`` is the full count (before windowing) so a client can detect that
    more pages exist. An out-of-range ``offset`` yields an empty window rather
    than raising. Never mutates ``items``.
    """
    off = clamp_offset(offset)
    lim = clamp_limit(limit)
    total = len(items)
    window = items[off : off + lim]
    return window, {"total": total, "offset": off, "limit": lim}
