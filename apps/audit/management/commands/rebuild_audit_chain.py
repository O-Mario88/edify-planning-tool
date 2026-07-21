"""Re-link the tamper-evident audit chain after a detected break.

The chain is tamper-EVIDENT, not tamper-proof: a concurrency race (duplicate
seq values — closed by the unique constraint on AuditLog.seq) broke
verification honestly rather than silently. This rebuild re-orders rows by
(created_at, id), recomputes seq and the hash links, and reports the before
and after verification states. Dry-run by default.
"""

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Re-sequence and re-hash the tamper-evident audit chain."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        from apps.audit.models import AuditLog
        from apps.audit.services import verify_chain
        from apps.core.audit_hash import (
            CanonicalAuditFields,
            canonical_audit,
            chain_hash,
        )

        state = verify_chain()
        self.stdout.write(f"before: {state}")
        if state.get("ok"):
            return
        if not opts["apply"]:
            self.stdout.write("DRY RUN — pass --apply to rebuild.")
            return
        with transaction.atomic():
            rows = list(
                AuditLog.objects.select_for_update().order_by("created_at", "id")
            )
            # Clear seqs first so the unique constraint cannot collide with
            # a not-yet-renumbered row mid-pass.
            AuditLog.objects.update(seq=None)
            prev_hash = ""
            for i, row in enumerate(rows, start=1):
                fields = CanonicalAuditFields(
                    action=row.action,
                    subject_kind=row.subject_kind,
                    subject_id=row.subject_id,
                    actor_id=row.actor_id,
                    actor_role=row.actor_role,
                    success=row.success,
                    reason=row.reason,
                    ip_address=row.ip_address,
                    user_agent=row.user_agent,
                    correlation_id=row.correlation_id,
                    payload=row.payload,
                )
                row.seq = i
                row.prev_hash = prev_hash or None
                row.hash = chain_hash(prev_hash, canonical_audit(fields))
                row.save(update_fields=["seq", "prev_hash", "hash"])
                prev_hash = row.hash
        self.stdout.write(f"after: {verify_chain()}")
