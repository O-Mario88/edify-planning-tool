"""Who's Online forgets the browser's machinery (2026-09-29).

Until 2026-09-28 a person's last page could be "/sw.js": the browser checks
its service worker in the background, with the session cookie, and that
request was recorded like a page. Who's Online (#162) then credited the next
minutes to it, as a part of the tool called "Sw.Js", and the defect beacon's
POST read as "Viewing Support · client defect". Those minutes cannot be
given back to the part of the tool they were spent on, so the rows are
removed, and the stored machinery pages are cleared so they are credited to
nothing again. ``apps.accounts.presence.is_untracked_path`` is the rule.

The live helpers are pure functions of a path; the historical models do the
writing. On a database with no such rows nothing happens. Reverse is a no-op.
"""

from django.db import migrations
from django.db.models import Q

MACHINERY_PAGES = (
    ("/support/client-defect", "POST /support/client-defect"),
    ("/support/client-defect", ""),
)


def forget(apps, schema_editor):
    from apps.accounts.presence import is_untracked_path
    from apps.accounts.presence_labels import describe

    User = apps.get_model("accounts", "User")
    PresenceTime = apps.get_model("accounts", "PresenceTime")

    stale = [
        pk
        for pk, path in User.objects.exclude(last_seen_path="")
        .exclude(last_seen_path__isnull=True)
        .values_list("pk", "last_seen_path")
        if is_untracked_path(path)
    ]
    User.objects.filter(pk__in=stale).update(last_seen_path="", last_seen_action="")

    # A file's section keeps its dot ("Sw.Js", "Manifest.Webmanifest"); no
    # page of the tool has one.
    rows = Q(section__contains=".")
    for path, action in MACHINERY_PAGES:
        label = describe(path, action)
        rows |= Q(section=label["section"], working_on=label["working_on"])
    removed, _ = PresenceTime.objects.filter(rows).delete()
    if stale or removed:
        print(
            f"\nWho's Online: cleared {len(stale)} machinery page(s), "
            f"removed {removed} machinery time record(s)."
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0032_presence_time")]

    operations = [migrations.RunPython(forget, migrations.RunPython.noop)]
