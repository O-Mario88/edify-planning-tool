"""Rows written together still announce themselves."""

from __future__ import annotations


def saved_together(model, rows) -> None:
    """Send `post_save` for rows `bulk_create` has just written.

    `bulk_create` sends no signals. Rows that used to be created one at a
    time announced themselves to whatever listens (an advance's snapshot
    projection, the traceability matrix's record of what a route writes);
    written together, they still do."""
    from django.db.models.signals import post_save

    for row in rows:
        post_save.send(
            sender=model,
            instance=row,
            created=True,
            update_fields=None,
            raw=False,
            using=row._state.db or "default",
        )


__all__ = ["saved_together"]
