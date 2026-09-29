"""Who's Online gives the minutes after a sign-in to the Dashboard (2026-09-29).

A sign-in is recorded (``record_login``) with the person on the Dashboard,
where every sign-in lands. The sign-in's own POST then passed through the
session middleware like any write and replaced that page with "/login", so
the time until the person's next beat — up to ten minutes of reading the
Dashboard — was credited to "Sign-in · Signing in", and a two-step code's
POST to "Sign-in · Verifying work". Signing in and out are no longer pages
(``apps.accounts.presence.is_untracked_path``). This moves the time already
recorded under "Sign-in" to "Dashboard · Viewing Dashboard" on the same day,
and puts anyone whose last page is a sign-in back on the Dashboard, as
``record_login`` left them.

The live helpers are pure functions of a path; the historical models do the
writing. On a database with no such rows nothing happens. Reverse is a no-op.
"""

from django.db import migrations
from django.db.models import F


def move(apps, schema_editor):
    from apps.accounts.presence_labels import describe

    User = apps.get_model("accounts", "User")
    PresenceTime = apps.get_model("accounts", "PresenceTime")

    sign_in = describe("/login")["section"]
    landing = describe("/dashboard")
    moved = 0
    for row in PresenceTime.objects.filter(section=sign_in):
        target = PresenceTime.objects.filter(
            user_id=row.user_id,
            day=row.day,
            section=landing["section"][:64],
            working_on=landing["working_on"][:128],
        )
        if not target.update(seconds=F("seconds") + row.seconds):
            PresenceTime.objects.create(
                user_id=row.user_id,
                day=row.day,
                section=landing["section"][:64],
                working_on=landing["working_on"][:128],
                seconds=row.seconds,
            )
        row.delete()
        moved += 1

    signed_in = User.objects.filter(last_seen_path__startswith="/login").update(
        last_seen_path="/dashboard", last_seen_action=""
    )
    if moved or signed_in:
        print(
            f"\nWho's Online: moved {moved} sign-in time record(s) to the "
            f"Dashboard, put {signed_in} person(s) back on it."
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0033_forget_browser_machinery_presence")]

    operations = [migrations.RunPython(move, migrations.RunPython.noop)]
