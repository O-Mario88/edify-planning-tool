from types import SimpleNamespace
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from apps.frontend.work_plan_tables import detail_fields, grouped_tables, work_plan_action


class WorkPlanTablesTests(SimpleTestCase):
    def activity(self, **kwargs):
        values = dict(id='activity-1', activity_type='school_visit', school_id='pk-1',
                      school=SimpleNamespace(name='Grace', school_id='SCH-42'),
                      cluster_id=None, status='scheduled', reschedule_count=0,
                      schools_invited=3, cluster_school_count_snapshot=9,
                      teachers_per_school=2, leaders_per_school=1, other_per_school=0,
                      delivery_type='staff', venue='Hall')
        return SimpleNamespace(**(values | kwargs))

    def test_explicit_non_school_and_cluster_classification(self):
        self.assertEqual(detail_fields(self.activity(), 'non_school', 'Q4')['detail_group'], 'non_school')
        self.assertEqual(detail_fields(self.activity(activity_type='cluster_training'), 'school', 'Q4')['detail_group'], 'cluster')
        self.assertEqual(detail_fields(self.activity(), 'school', 'Q4')['school_code'], 'SCH-42')

    def test_invited_count_not_cluster_membership_or_attendance(self):
        row = detail_fields(self.activity(), 'school', 'Q4')
        self.assertEqual((row['schools_invited'], row['teachers_invited'], row['leaders_invited'], row['others_invited']), (3, 6, 3, 0))
        row = detail_fields(self.activity(schools_invited=None, teachers_per_school=None), 'school', 'Q4')
        self.assertEqual(row['schools_invited'], 9)
        self.assertIsNone(row['teachers_invited'])

    def test_terminal_status_precedes_reschedule_history(self):
        for status, label in [('cancelled', 'Cancelled'), ('closed', 'Complete'), ('scheduled', 'Rescheduled')]:
            self.assertEqual(detail_fields(self.activity(status=status, reschedule_count=1), 'school', 'Q4')['delivery_status'], label)

    def test_owner_edits_existing_activity_supervisor_composes_and_readonly_does_not_act(self):
        activity = self.activity()
        action = work_plan_action(activity, owned=True, enabled=True)
        self.assertEqual(action['url'], '/my-plan/activity-1/reschedule-drawer')
        action = work_plan_action(activity, owned=False, enabled=True, recipient='person-1', recipient_name='Jane')
        self.assertEqual(action['text'], 'Send to Jane')
        self.assertIn('context_id=activity-1', action['url'])
        self.assertIn('to=person-1', action['url'])
        self.assertIsNone(work_plan_action(activity, owned=False, enabled=False, recipient='person-1'))
        self.assertEqual(work_plan_action(self.activity(status='completed'), owned=True, enabled=True)['text'], 'View')

    def test_three_tables_always_render_with_correct_column_counts(self):
        from html.parser import HTMLParser
        class TableHeaders(HTMLParser):
            def __init__(self):
                super().__init__(); self.counts=[]
            def handle_starttag(self, tag, attrs):
                if tag == 'table': self.counts.append(0)
                if tag == 'th' and ('scope', 'col') in attrs: self.counts[-1] += 1
        html = render_to_string('partials/work_plan/detail_tables.html', {'detail_tables': grouped_tables([]), 'period_label': 'Q4'})
        parser=TableHeaders(); parser.feed(html)
        self.assertEqual(parser.counts, [11, 12, 6])
        self.assertEqual(html.count('No activities in this group'), 3)

    def test_message_recipient_prefill_respects_allowed_recipients(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        from django.test import RequestFactory
        from apps.frontend.views.message_views import _compose_context
        with ExitStack() as stack:
            allowed = [{'id': 'allowed', 'name': 'Jane', 'role': 'CCEO'}]
            for name, result in [('recipients', allowed), ('categories_for_role', []), ('drafts_for_user', []), ('search_context_records', [])]:
                stack.enter_context(patch('apps.frontend.views.message_views.services.' + name, return_value=result))
            for recipient, expected in [('allowed', allowed), ('outside-scope', [])]:
                request = RequestFactory().get('/messages/new', {'to': recipient})
                request.user = SimpleNamespace(id='viewer')
                self.assertEqual(_compose_context(request)['pre_to'], expected)
