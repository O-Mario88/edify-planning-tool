"""The route check of a day follows the save that changed the day.

Working a day's route out (order, distance, whether it fits, what to suggest)
is advice beside the plan. It ran inside every save that priced a day of
school visits, about thirty statements, and an in-school training moved
between two days paid for it twice. The days are now remembered while the
save runs and worked out once it has committed, off the request
(apps.routes.after_save).

`ROUTE_CHECK_AFTER_SAVE` is off under the test runner, where a test's own
transaction never commits; these tests turn it on and run the commit's
callbacks themselves.
"""

from __future__ import annotations

from datetime import date
from unittest import mock

from django.db import transaction
from django.test import TestCase, override_settings

from apps.routes import after_save
from apps.routes.engine import DailyVisitRouteBatchService

MON, TUE = date(2026, 8, 3), date(2026, 8, 4)


class _Checked(TestCase):
    def setUp(self):
        patcher = mock.patch.object(DailyVisitRouteBatchService, "rebuild_for")
        self.rebuild = patcher.start()
        self.addCleanup(patcher.stop)

    def days(self):
        return sorted(call.args for call in self.rebuild.call_args_list)


@override_settings(ROUTE_CHECK_AFTER_SAVE=True)
class AfterTheSaveTest(_Checked):
    def test_nothing_is_worked_out_until_the_save_commits(self):
        with self.captureOnCommitCallbacks() as at_commit:
            with transaction.atomic():
                after_save.rebuild_after_save("officer-1", MON)
                self.rebuild.assert_not_called()
        self.rebuild.assert_not_called()
        for callback in at_commit:
            callback()
        after_save.wait()
        self.assertEqual(self.days(), [("officer-1", MON)])

    def test_a_day_changed_several_times_is_worked_out_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                after_save.rebuild_after_save("officer-1", MON)
                after_save.rebuild_after_save("officer-1", TUE)
                after_save.rebuild_after_save("officer-1", MON)
        after_save.wait()
        self.assertEqual(self.days(), [("officer-1", MON), ("officer-1", TUE)])

    def test_a_save_that_is_undone_checks_nothing(self):
        class Undo(Exception):
            pass

        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    after_save.rebuild_after_save("officer-1", MON)
                    raise Undo
            except Undo:
                pass
        after_save.wait()
        self.rebuild.assert_not_called()

    def test_outside_a_save_it_is_worked_out_at_once(self):
        after_save.rebuild_after_save("officer-1", MON)
        self.assertEqual(self.days(), [("officer-1", MON)])

    def test_a_route_that_cannot_be_worked_out_breaks_nothing(self):
        self.rebuild.side_effect = RuntimeError("no coordinates")
        with self.assertLogs("apps.routes.after_save", level="WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    after_save.rebuild_after_save("officer-1", MON)
            after_save.wait()


class TheSwitchTest(_Checked):
    @override_settings(ROUTE_CHECK_AFTER_SAVE=False)
    def test_off_the_route_is_worked_out_inside_the_save(self):
        with transaction.atomic():
            after_save.rebuild_after_save("officer-1", MON)
            self.assertEqual(self.days(), [("officer-1", MON)])
