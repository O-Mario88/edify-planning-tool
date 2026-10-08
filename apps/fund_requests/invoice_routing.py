"""Which Programme Lead a partner's invoice goes to.

Owner, 2026-10-08: an invoice "goes to the program lead for that region (The
PL own schools, schools of CCEOs under him)".

An invoice used to reach every Lead who supervised an officer named on any of
its activities, so one invoice for visits in two teams sat in both Leads'
queues and either could confirm all of it, the other team's schools included.
And a visit at a school the Lead holds themselves reached nobody: the rule
looked for the supervisor of the school's officer, and a Lead's supervisor is
the Country Director.

The rule here is about the school, as the owner states it:

1. The Lead is whoever holds the school, when a Lead holds it.
2. Otherwise it is the Lead the school's officer reports to.
3. Work at no single school (a cluster training the partner facilitates) goes
   by the officer who runs it, the same way.

A Lead is someone who HOLDS the Programme Lead role, whichever role their
account is switched to (``apps.core.role_holding``), and a reporting line
counts only when it ends at one: Impact Assessment and the Regional Vice
President hold oversight lines over the same people, and neither confirms a
partner's invoice.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lead:
    """A Programme Lead an invoice is addressed to."""

    staff_id: str
    user_id: str
    name: str


class LeadResolver:
    """The Lead of each activity, for a batch of activities, in five queries.

    Built from the ids the activities name, because an invoice lists a
    period's work and a lookup per line is a query per line.
    """

    def __init__(self, activities):
        from apps.accounts.models import (
            StaffProfile,
            StaffSchoolAssignment,
            StaffSupervisorAssignment,
        )
        from apps.core.rbac import EdifyRole
        from apps.core.role_holding import holds_role, holds_role_q

        activities = list(activities)
        school_ids = {a.school_id for a in activities if a.school_id}
        # `responsible_staff_id` and `monitored_by_staff_id` hold a People
        # record's id or a user's id, depending on who wrote them
        # (apps.core.scoping.owner_ids): both are read.
        officer_ids = {
            value
            for a in activities
            for value in (a.responsible_staff_id, a.monitored_by_staff_id)
            if value
        }

        #: school id -> the People records that hold it, steadily ordered.
        self._holders: dict[str, list[str]] = {}
        for school_id, staff_id in (
            StaffSchoolAssignment.objects.filter(school_id__in=school_ids)
            .order_by("staff__user__name", "staff_id")
            .values_list("school_id", "staff_id")
        ):
            self._holders.setdefault(school_id, []).append(staff_id)

        holder_ids = {sid for ids in self._holders.values() for sid in ids}
        self._lead: dict[str, Lead] = {}
        #: either id of a person -> their People record's id.
        self._staff_for: dict[str, str] = {}
        from django.db.models import Q

        profiles = StaffProfile.objects.filter(
            Q(id__in=holder_ids | officer_ids) | Q(user_id__in=officer_ids),
            deleted_at__isnull=True,
        ).select_related("user")
        for profile in profiles:
            self._staff_for[profile.id] = profile.id
            if profile.user_id:
                self._staff_for[profile.user_id] = profile.id
            if holds_role(profile.user, EdifyRole.COUNTRY_PROGRAM_LEAD):
                self._lead[profile.id] = _lead(profile)

        #: People record id -> the Lead they report to.
        self._reports_to: dict[str, Lead] = {}
        links = (
            StaffSupervisorAssignment.objects.filter(
                holds_role_q(EdifyRole.COUNTRY_PROGRAM_LEAD, "supervisor__user"),
                supervisee_id__in=set(self._staff_for.values()),
                supervisor__deleted_at__isnull=True,
            )
            .select_related("supervisor__user")
            .order_by("supervisor__user__name", "supervisor_id")
        )
        for link in links:
            self._reports_to.setdefault(link.supervisee_id, _lead(link.supervisor))

    def _lead_of_person(self, person_id) -> Lead | None:
        staff_id = self._staff_for.get(person_id or "")
        if not staff_id:
            return None
        return self._lead.get(staff_id) or self._reports_to.get(staff_id)

    def lead_of(self, activity) -> Lead | None:
        """The Lead this activity's invoice line goes to, or None when the
        school has no officer or the officer reports to no Lead."""
        holders = self._holders.get(activity.school_id or "", [])
        # A Lead who holds the school themselves comes before the Lead of a
        # second officer who shares it.
        for staff_id in holders:
            if staff_id in self._lead:
                return self._lead[staff_id]
        for staff_id in holders:
            if staff_id in self._reports_to:
                return self._reports_to[staff_id]
        # No holder on record, or work at no single school: the officer the
        # activity itself names.
        for person_id in (
            activity.monitored_by_staff_id,
            activity.responsible_staff_id,
        ):
            lead = self._lead_of_person(person_id)
            if lead is not None:
                return lead
        return None


def _lead(profile) -> Lead:
    user = profile.user
    return Lead(
        staff_id=profile.id,
        user_id=profile.user_id,
        name=getattr(user, "name", "") or getattr(user, "email", "") or "",
    )


def split_by_lead(items, activity_of=lambda item: item["activity"]):
    """``items`` folded by the Lead each goes to: ``[(Lead | None, [items])]``,
    Leads by name and the lines with no Lead last. One invoice is raised for
    each, so a Lead confirms their own schools and nobody else's."""
    items = list(items)
    resolver = LeadResolver(activity_of(item) for item in items)
    groups: dict[str, tuple[Lead | None, list]] = {}
    for item in items:
        lead = resolver.lead_of(activity_of(item))
        key = lead.staff_id if lead else ""
        groups.setdefault(key, (lead, []))[1].append(item)
    return sorted(
        groups.values(),
        key=lambda group: (group[0] is None, group[0].name if group[0] else ""),
    )
