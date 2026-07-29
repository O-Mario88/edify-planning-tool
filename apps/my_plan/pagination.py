"""Ten rows a card, and pages that run as far as the person has planned.

My Plan showed every activity in the period in one column. A CCEO who has
planned two months ahead got a page they had to scroll past to reach the next
card, and the week they were actually working was buried in it.

So each card shows ten and the rest sit behind pages. The page count is not a
fixed window: it runs to the last activity the person has planned, which is
what "up to where they stopped planning" means. Someone who planned three
weeks gets three weeks of pages; someone who planned three months gets three
months. Nothing is hidden behind a period filter they have to discover.
"""

from __future__ import annotations

PAGE_SIZE = 10


def paginate(rows: list, page: int = 1, page_size: int = PAGE_SIZE) -> dict:
    """One card's slice, plus what the template needs to draw its pager.

    Out-of-range pages clamp rather than erroring: a stale link from a card
    that has since emptied should show the last real page, not a 404 in the
    middle of a working list.
    """
    rows = list(rows)
    total = len(rows)
    page_size = max(1, int(page_size or PAGE_SIZE))
    page_count = max(1, -(-total // page_size))  # ceiling division
    current = min(max(1, int(page or 1)), page_count)

    start = (current - 1) * page_size
    window = rows[start : start + page_size]

    return {
        "rows": window,
        "page": current,
        "page_count": page_count,
        "page_size": page_size,
        "total": total,
        "has_previous": current > 1,
        "has_next": current < page_count,
        "previous_page": current - 1,
        "next_page": current + 1,
        # Both ends are 1-based and inclusive, for "11–20 of 47".
        "first_index": start + 1 if window else 0,
        "last_index": start + len(window),
        # A single page needs no pager at all; saying so here keeps the
        # decision out of the template.
        "paginated": page_count > 1,
        "pages": list(range(1, page_count + 1)),
    }


def page_from(query: dict, key: str) -> int:
    """Read one card's page number, tolerating anything a URL can carry."""
    try:
        return max(1, int((query or {}).get(key) or 1))
    except (TypeError, ValueError):
        return 1
