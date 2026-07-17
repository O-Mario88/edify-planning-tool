"""FieldDebriefService — submission, scoping, and recommendation acceptance
for the Field Debrief workflow (mandate §1-§13, §20).

Notification routing is deliberately narrow: every eligible-reader role
(CD/HR/IA/RVP) gets debriefs through their own *scoped queryset* (computed
live, matching this codebase's "compute on read" convention everywhere
else) rather than a DailyDebriefRecipient/notification row per debrief per
role — the mandate is explicit that RVP "should not normally read every
routine daily report by default" and HR/IA are "read-only" audiences, not
notification targets, for routine submissions. Recipient rows + real
notifications are created only for genuinely actionable routing: the
submitter's supervising PL, a role a support request was addressed to, and
whatever `risk_level`/restricted-incident implies.
"""

from __future__ import annotations


from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole

from .models import (
    DailyDebrief,
    DailyDebriefActivityLink,
    DailyDebriefChallenge,
    DailyDebriefCommitment,
    DailyDebriefRecipient,
    DailyDebriefSupportRequest,
    DebriefKind,
    DebriefStatus,
    DebriefType,
    RecommendationStatus,
    RestrictedIncidentCategory,
    RiskLevel,
)

SUBMITTER_ROLES = (
    EdifyRole.CCEO.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.PARTNER_ADMIN.value,
    EdifyRole.PARTNER_FIELD_OFFICER.value,
    EdifyRole.PROJECT_COORDINATOR.value,
)
STAFF_SUBMITTER_ROLES = (
    EdifyRole.CCEO.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.PROJECT_COORDINATOR.value,
)
PARTNER_ROLES = (EdifyRole.PARTNER_ADMIN.value, EdifyRole.PARTNER_FIELD_OFFICER.value)

# The leadership roles that may manage a debrief's lifecycle (same set the
# detail page's `can_manage` flag and the action-routing service use).
DEBRIEF_MANAGER_ROLES = (
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.HUMAN_RESOURCES.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.REGIONAL_VICE_PRESIDENT.value,
    EdifyRole.ADMIN.value,
)

# Restricted-incident categories route ONLY to these roles — never the
# general peer feed, team view, or routine dashboard queryset (§7-J, §23).
RESTRICTED_ROUTING = {
    RestrictedIncidentCategory.SAFEGUARDING: (
        EdifyRole.HUMAN_RESOURCES.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
    ),
    RestrictedIncidentCategory.FRAUD: (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.PROGRAM_ACCOUNTANT.value,
    ),
    RestrictedIncidentCategory.STAFF_SAFETY: (
        EdifyRole.HUMAN_RESOURCES.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
    ),
    RestrictedIncidentCategory.DATA_INTEGRITY: (
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
    ),
    RestrictedIncidentCategory.PARTNER_MISCONDUCT: (EdifyRole.COUNTRY_DIRECTOR.value,),
    RestrictedIncidentCategory.SCHOOL_COMPLAINT: (EdifyRole.COUNTRY_DIRECTOR.value,),
    RestrictedIncidentCategory.OTHER: (EdifyRole.COUNTRY_DIRECTOR.value,),
}

RISK_ROUTING = {
    RiskLevel.PL_ATTENTION: (),  # PL already routed as the default recipient
    RiskLevel.CD_ATTENTION: (EdifyRole.COUNTRY_DIRECTOR.value,),
    RiskLevel.IA_ATTENTION: (EdifyRole.IMPACT_ASSESSMENT.value,),
    RiskLevel.HR_ATTENTION: (EdifyRole.HUMAN_RESOURCES.value,),
    RiskLevel.FINANCE_ATTENTION: (EdifyRole.PROGRAM_ACCOUNTANT.value,),
    RiskLevel.CRITICAL: (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.HUMAN_RESOURCES.value,
        EdifyRole.REGIONAL_VICE_PRESIDENT.value,
    ),
}


def _staff_profile(principal):
    from apps.accounts.models import StaffProfile

    return StaffProfile.objects.filter(user_id=principal.user_id).first()


def supervising_pl(staff_profile) -> "object | None":
    from apps.accounts.models import StaffSupervisorAssignment

    if not staff_profile:
        return None
    link = (
        StaffSupervisorAssignment.objects.filter(supervisee=staff_profile)
        .select_related("supervisor__user")
        .first()
    )
    return link.supervisor if link else None


def team_staff_ids(supervisor_staff_id: str) -> list[str]:
    from apps.accounts.models import StaffSupervisorAssignment

    return list(
        StaffSupervisorAssignment.objects.filter(
            supervisor_id=supervisor_staff_id
        ).values_list("supervisee_id", flat=True)
    )


class FieldDebriefService:
    @staticmethod
    def can_submit(principal) -> bool:
        return getattr(principal, "active_role", "") in SUBMITTER_ROLES

    @staticmethod
    def submit(principal, data: dict) -> DailyDebrief:
        """Create a debrief plus its child rows (activity links, structured
        challenges, commitments, support requests), then route it. A debrief
        may be submitted even while its linked activity's own Evidence/SF-ID/
        accountability chain is still pending (§8) — Field Debrief never
        blocks or replaces that chain."""
        role = getattr(principal, "active_role", "")
        if role not in SUBMITTER_ROLES:
            raise Forbidden("Your role cannot submit a Field Debrief.")

        title = (data.get("title") or "").strip()
        if not title:
            raise BadRequest("A debrief title is required.")

        activity_ids = [a for a in data.get("activity_ids") or [] if a]
        for aid in activity_ids:
            FieldDebriefService._assert_can_debrief_activity(principal, role, aid)

        sp = _staff_profile(principal)
        is_restricted = bool(data.get("is_restricted_incident"))
        restricted_category = data.get("restricted_incident_category") or None
        if is_restricted and not restricted_category:
            raise BadRequest("Select an incident category for a restricted incident.")

        partner_id = None
        if role in PARTNER_ROLES:
            from apps.core.scoping import resolve_partner_ids

            # The submission form carries no partner_id input — a partner
            # submitter's own partner is resolved the same canonical way
            # scoped_queryset() reads it back, so a partner always sees their
            # own submission. data["partner_id"] can still override (e.g. a
            # user linked to more than one active partner).
            partner_id = data.get("partner_id") or next(
                iter(resolve_partner_ids(principal)), None
            )

        debrief = DailyDebrief.objects.create(
            fy=get_operational_fy(),
            date=timezone.now(),
            submitted_by_user_id=principal.user_id,
            submitted_by_role=role,
            staff_id=sp.id if sp else None,
            partner_id=partner_id,
            debrief_type=DebriefType.PARTNER
            if role in PARTNER_ROLES
            else DebriefType.STAFF,
            kind=data.get("kind") or DebriefKind.ACTIVITY,
            status=DebriefStatus.RESTRICTED_INCIDENT
            if is_restricted
            else DebriefStatus.SUBMITTED,
            title=title,
            summary=data.get("summary"),
            what_happened=data.get("what_happened"),
            what_went_well=data.get("what_went_well"),
            what_did_not_go_well=data.get("what_did_not_go_well"),
            support_needed=data.get("support_needed"),
            recommendations=data.get("recommendations"),
            next_action=data.get("next_action"),
            linked_school_ids=data.get("school_ids") or [],
            linked_activity_ids=activity_ids,
            submitted_at=timezone.now(),
            completion_status=data.get("completion_status") or None,
            incomplete_reason=data.get("incomplete_reason"),
            actual_start_time=data.get("actual_start_time") or None,
            actual_end_time=data.get("actual_end_time") or None,
            participants_summary=data.get("participants_summary"),
            what_was_done=data.get("what_was_done"),
            intended_purpose=data.get("intended_purpose"),
            purpose_achieved=data.get("purpose_achieved"),
            what_observed=data.get("what_observed"),
            what_improved=data.get("what_improved"),
            what_remains_weak=data.get("what_remains_weak"),
            what_surprised=data.get("what_surprised"),
            support_needed_next=data.get("support_needed_next"),
            intervention_tags=data.get("intervention_tags") or [],
            expected_participants=data.get("expected_participants") or None,
            actual_participants=data.get("actual_participants") or None,
            school_leaders_present=data.get("school_leaders_present") or None,
            teachers_present=data.get("teachers_present") or None,
            other_participants_present=data.get("other_participants_present") or None,
            engagement_level=data.get("engagement_level") or None,
            attendance_concerns=data.get("attendance_concerns"),
            planned_route=data.get("planned_route"),
            actual_route=data.get("actual_route"),
            schools_planned_count=data.get("schools_planned_count") or None,
            schools_reached_count=data.get("schools_reached_count") or None,
            travel_start_time=data.get("travel_start_time") or None,
            travel_end_time=data.get("travel_end_time") or None,
            estimated_travel_minutes=data.get("estimated_travel_minutes") or None,
            actual_travel_minutes=data.get("actual_travel_minutes") or None,
            route_quality=data.get("route_quality"),
            transport_issue=data.get("transport_issue"),
            immediate_result=data.get("immediate_result"),
            follow_up_date=data.get("follow_up_date") or None,
            follow_up_owner_id=data.get("follow_up_owner_id"),
            recommended_next_activity_type=data.get("recommended_next_activity_type")
            or None,
            recommended_intervention=data.get("recommended_intervention") or None,
            recommendation_status=(
                RecommendationStatus.PROPOSED
                if data.get("recommended_next_activity_type")
                and data.get("recommended_next_activity_type") != "no_further_action"
                else RecommendationStatus.NONE
            ),
            key_success=data.get("key_success"),
            key_lesson_learned=data.get("key_lesson_learned"),
            practice_worth_repeating=data.get("practice_worth_repeating"),
            innovation_observed=data.get("innovation_observed"),
            potential_mscs_flag=bool(data.get("potential_mscs_flag")),
            potential_mscs_title=data.get("potential_mscs_title"),
            potential_mscs_narrative=data.get("potential_mscs_narrative"),
            potential_champion_flag=bool(data.get("potential_champion_flag")),
            potential_champion_note=data.get("potential_champion_note"),
            potential_partner_success_flag=bool(
                data.get("potential_partner_success_flag")
            ),
            risk_level=data.get("risk_level") or RiskLevel.NONE,
            is_restricted_incident=is_restricted,
            restricted_incident_category=restricted_category,
        )

        for aid in activity_ids:
            from apps.activities.models import Activity

            activity = Activity.objects.filter(id=aid).first()
            DailyDebriefActivityLink.objects.create(
                debrief=debrief,
                activity_id=aid,
                school_id=activity.school_id if activity else None,
            )

        for c in data.get("challenges") or []:
            if not c.get("challenge_type"):
                continue
            DailyDebriefChallenge.objects.create(
                debrief=debrief,
                challenge_type=c["challenge_type"],
                description=c.get("description"),
                severity=c.get("severity") or "medium",
                immediate_response=c.get("immediate_response"),
                resolved=bool(c.get("resolved")),
                follow_up_owner_id=c.get("follow_up_owner_id"),
            )

        for cm in data.get("commitments") or []:
            if not cm.get("party") or not cm.get("commitment_text"):
                continue
            DailyDebriefCommitment.objects.create(
                debrief=debrief,
                party=cm["party"],
                commitment_text=cm["commitment_text"],
                follow_up_date=cm.get("follow_up_date") or None,
                follow_up_owner_id=cm.get("follow_up_owner_id"),
            )

        for sr in data.get("support_requests") or []:
            if not sr.get("requested_from_role") or not sr.get("support_type"):
                continue
            DailyDebriefSupportRequest.objects.create(
                debrief=debrief,
                requested_from_role=sr["requested_from_role"],
                support_type=sr["support_type"],
                note=sr.get("note"),
            )

        if debrief.potential_mscs_flag:
            FieldDebriefService._create_mscs_draft(principal, debrief)

        FieldDebriefService._route(principal, debrief, sp)
        return debrief

    @staticmethod
    def _assert_can_debrief_activity(principal, role: str, activity_id: str) -> None:
        """§3 scope check — a submitter may only debrief activities that are
        actually theirs (or, for a CCEO, their own or their Partner's)."""
        from apps.activities.models import Activity

        activity = Activity.objects.filter(id=activity_id).first()
        if not activity:
            raise BadRequest(f"Unknown activity: {activity_id}")
        if role == EdifyRole.ADMIN.value:
            return
        sp = _staff_profile(principal)
        owner_ids = {principal.user_id}
        if sp:
            owner_ids.add(sp.id)
        if role in PARTNER_ROLES:
            from apps.core.scoping import resolve_partner_ids

            if (
                activity.assigned_partner_id
                and activity.assigned_partner_id in resolve_partner_ids(principal)
            ):
                return
            raise Forbidden(
                "You may only debrief activities assigned to your Partner organization."
            )
        if (
            activity.responsible_staff_id in owner_ids
            or activity.monitored_by_staff_id in owner_ids
        ):
            return
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value and sp:
            if activity.responsible_staff_id in team_staff_ids(sp.id):
                return
        raise Forbidden(
            "You may only debrief activities assigned to or supervised by you."
        )

    @staticmethod
    def _create_mscs_draft(principal, debrief: DailyDebrief) -> None:
        """ "Create an MSCS draft recommendation. Do not count it as an
        approved MSCS" (§7-I) — reuses the existing MSCS model exactly;
        approval still goes through the normal Targets MSCS review."""
        from apps.targets.models import MostSignificantChangeStory

        story = MostSignificantChangeStory.objects.create(
            user_id=principal.user_id,
            school_id=debrief.linked_school_ids[0]
            if debrief.linked_school_ids
            else None,
            title=debrief.potential_mscs_title or debrief.title,
            narrative=debrief.potential_mscs_narrative or debrief.key_success or "",
            story_date=debrief.date.date(),
        )
        debrief.mscs_draft_story_id = story.id
        debrief.save(update_fields=["mscs_draft_story_id"])

    @staticmethod
    def _route(principal, debrief: DailyDebrief, sp) -> None:
        from apps.notifications.services import WorkflowNotificationService

        recipients = []  # list[(user_id, role, reason, action_required)]
        country = sp.country if sp else None
        pl = supervising_pl(sp) if sp else None

        if pl and pl.user_id and pl.user_id != principal.user_id:
            recipients.append(
                (
                    pl.user_id,
                    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                    "Supervising Program Lead",
                    True,
                )
            )
        elif principal.active_role in PARTNER_ROLES:
            # Partner debriefs route to the CCEO managing the assigned school/activity.
            for link in debrief.activity_links.select_related("activity"):
                owner_id = link.activity.responsible_staff_id if link.activity else None
                if owner_id:
                    recipients.append(
                        (owner_id, EdifyRole.CCEO.value, "Managing CCEO", True)
                    )

        def _resolve_role(role: str) -> list[str]:
            """Program Lead always means *this submitter's own* supervising
            PL (there are many PLs org-wide). CD/IA/HR/Accountant are one
            holder per country, so resolve scoped to the submitter's own
            country. RVP oversees a multi-country region with no simple
            country match on their own profile, and there are typically
            only one or two RVPs org-wide — broadcast unscoped rather than
            risk silently excluding the real one on a rare, high-priority
            escalation."""
            if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
                return [pl.user_id] if pl and pl.user_id else []
            if role == EdifyRole.REGIONAL_VICE_PRESIDENT.value:
                return _users_with_role(role)
            return _users_with_role(role, country=country)

        if debrief.is_restricted_incident:
            for role in RESTRICTED_ROUTING.get(
                debrief.restricted_incident_category, ()
            ):
                for uid in _resolve_role(role):
                    recipients.append((uid, role, "Restricted incident", True))
        else:
            for role in RISK_ROUTING.get(debrief.risk_level, ()):
                for uid in _resolve_role(role):
                    recipients.append(
                        (
                            uid,
                            role,
                            f"Risk level: {debrief.get_risk_level_display()}",
                            True,
                        )
                    )
            for sr in debrief.support_requests.all():
                for uid in _resolve_role(sr.requested_from_role):
                    recipients.append(
                        (
                            uid,
                            sr.requested_from_role,
                            f"Support requested: {sr.get_support_type_display()}",
                            True,
                        )
                    )

        seen = set()
        for user_id, role, reason, action_required in recipients:
            key = (user_id, reason)
            if key in seen or not user_id:
                continue
            seen.add(key)
            DailyDebriefRecipient.objects.create(
                debrief=debrief,
                recipient_user_id=user_id,
                recipient_role=role,
                routing_reason=reason,
                action_required=action_required,
            )
            WorkflowNotificationService.trigger(
                event_type="field_debrief_routed",
                category="field_debrief",
                priority="high"
                if debrief.risk_level in (RiskLevel.CRITICAL,)
                or debrief.is_restricted_incident
                else "normal",
                title=f"Field Debrief: {debrief.title}",
                body=f"{debrief.submitted_by_role} debrief — {reason}.",
                context_type="field_debrief",
                context_id=debrief.id,
                recipients=[user_id],
            )

    @staticmethod
    def scoped_queryset(principal, params: dict | None = None) -> QuerySet:
        """§4/§5/§20 — the read-scope engine. Every dashboard/list view in
        this app must build its queryset through here, never query
        DailyDebrief directly, so scope rules live in exactly one place."""
        from apps.core.scoping import resolve_user_scope

        params = params or {}
        role = getattr(principal, "active_role", "")
        qs = DailyDebrief.objects.filter(deleted_at__isnull=True)
        sp = _staff_profile(principal)
        scope = resolve_user_scope(principal)

        if role == EdifyRole.ADMIN.value:
            pass  # unrestricted
        elif role == EdifyRole.HUMAN_RESOURCES.value:
            # HR is read-only audience for people/capacity signals — sees
            # everything non-restricted, plus restricted rows explicitly
            # routed to HR (safeguarding/staff-safety) via recipients.
            qs = qs.filter(
                Q(is_restricted_incident=False)
                | Q(recipients__recipient_user_id=principal.user_id)
            ).distinct()
        elif role == EdifyRole.IMPACT_ASSESSMENT.value:
            qs = qs.filter(
                Q(is_restricted_incident=False)
                | Q(recipients__recipient_user_id=principal.user_id)
            ).distinct()
        elif role == EdifyRole.COUNTRY_DIRECTOR.value:
            country_staff_ids = _country_staff_ids(sp.country if sp else None)
            qs = qs.filter(
                Q(staff_id__in=country_staff_ids)
                | Q(recipients__recipient_user_id=principal.user_id)
            ).distinct()
        elif role == EdifyRole.REGIONAL_VICE_PRESIDENT.value:
            # RVP: escalated/critical + explicitly routed only — never the
            # routine feed (§4 RVP section).
            qs = qs.filter(
                Q(risk_level=RiskLevel.CRITICAL)
                | Q(recipients__recipient_user_id=principal.user_id)
            ).distinct()
        elif role == EdifyRole.COUNTRY_PROGRAM_LEAD.value and sp:
            team_ids = team_staff_ids(sp.id)
            partner_ids = list(scope.partner_ids or [])
            qs = qs.filter(
                Q(staff_id=sp.id)
                | Q(staff_id__in=team_ids)
                | Q(partner_id__in=partner_ids)
            )
        elif role == EdifyRole.CCEO.value and sp:
            pl = supervising_pl(sp)
            peer_ids = team_staff_ids(pl.id) if pl else []
            qs = qs.filter(
                Q(staff_id=sp.id)
                | (Q(staff_id__in=peer_ids) & Q(is_restricted_incident=False))
            )
        elif role in PARTNER_ROLES:
            # `User` carries no `partner_id` attribute — the canonical link is
            # Partner.user_id, resolved by resolve_user_scope() into
            # scope.partner_ids (same source the PL branch above uses for its
            # own partner-visibility union).
            partner_ids = list(scope.partner_ids or [])
            qs = qs.filter(partner_id__in=partner_ids) if partner_ids else qs.none()
        elif role == EdifyRole.PROJECT_COORDINATOR.value and sp:
            qs = qs.filter(staff_id=sp.id)
        else:
            qs = qs.none()

        if params.get("mine"):
            qs = qs.filter(submitted_by_user_id=principal.user_id)
        if params.get("fy"):
            qs = qs.filter(fy=params["fy"])
        if params.get("district_id"):
            school_ids = _school_ids_in_district(params["district_id"])
            qs = qs.filter(linked_school_ids__overlap=school_ids)
        if params.get("staff_id"):
            qs = qs.filter(staff_id=params["staff_id"])
        if params.get("partner_id"):
            qs = qs.filter(partner_id=params["partner_id"])
        if params.get("risk_level"):
            qs = qs.filter(risk_level=params["risk_level"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("q"):
            q = params["q"]
            qs = qs.filter(Q(title__icontains=q) | Q(summary__icontains=q))
        return qs

    @staticmethod
    def can_read(principal, debrief: DailyDebrief) -> bool:
        return (
            FieldDebriefService.scoped_queryset(principal)
            .filter(id=debrief.id)
            .exists()
        )

    @staticmethod
    def get_one(principal, debrief_id: str) -> DailyDebrief:
        debrief = (
            FieldDebriefService.scoped_queryset(principal).filter(id=debrief_id).first()
        )
        if not debrief:
            raise NotFoundError("Debrief not found or not visible to you.")
        return debrief

    @staticmethod
    def request_clarification(principal, debrief_id: str, note: str) -> DailyDebrief:
        debrief = FieldDebriefService.get_one(principal, debrief_id)
        if getattr(principal, "active_role", "") not in (
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.ADMIN.value,
        ):
            raise Forbidden("Only a supervisor may request clarification.")
        debrief.status = DebriefStatus.CLARIFICATION_REQUESTED
        debrief.review_note = note
        debrief.reviewed_by_user_id = principal.user_id
        debrief.reviewed_at = timezone.now()
        debrief.save(
            update_fields=[
                "status",
                "review_note",
                "reviewed_by_user_id",
                "reviewed_at",
            ]
        )
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="field_debrief_clarification_requested",
            category="field_debrief",
            priority="high",
            title=f"Clarification needed: {debrief.title}",
            body=note or "Your supervisor requested clarification.",
            context_type="field_debrief",
            context_id=debrief.id,
            recipients=[debrief.submitted_by_user_id],
        )
        return debrief

    @staticmethod
    def update_after_clarification(
        principal, debrief_id: str, data: dict
    ) -> DailyDebrief:
        debrief = DailyDebrief.objects.filter(
            id=debrief_id, deleted_at__isnull=True
        ).first()
        if not debrief:
            raise NotFoundError("Debrief not found.")
        if debrief.submitted_by_user_id != principal.user_id:
            raise Forbidden("You may only update your own debrief.")
        if debrief.status != DebriefStatus.CLARIFICATION_REQUESTED:
            raise BadRequest("This debrief is not awaiting clarification.")
        for field in ("summary", "what_happened", "next_action"):
            if field in data:
                setattr(debrief, field, data[field])
        debrief.status = DebriefStatus.UPDATED
        debrief.save()
        if (
            debrief.reviewed_by_user_id
            and debrief.reviewed_by_user_id != principal.user_id
        ):
            from apps.notifications.services import WorkflowNotificationService

            WorkflowNotificationService.trigger(
                event_type="field_debrief_clarification_response",
                category="field_debrief",
                priority="normal",
                title=f"Clarification response: {debrief.title}",
                body="The submitter updated the debrief you asked to be clarified.",
                context_type="field_debrief",
                context_id=debrief.id,
                recipients=[debrief.reviewed_by_user_id],
            )
        return debrief

    @staticmethod
    def accept_recommendation(principal, debrief_id: str) -> "object":
        """§13 — accepting a recommended follow-up creates a real, draft
        Activity (never bypassing costing/scheduling — the responsible
        staff member still has to schedule and cost it through Planning
        like any other activity)."""
        from apps.activities.models import Activity, ActivityType

        debrief = FieldDebriefService.get_one(principal, debrief_id)
        role = getattr(principal, "active_role", "")
        if role not in (
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.ADMIN.value,
        ):
            raise Forbidden("Only a supervisor may accept a debrief recommendation.")
        if debrief.recommendation_status != RecommendationStatus.PROPOSED:
            raise BadRequest("This debrief has no pending recommendation.")

        type_map = {
            "school_visit": ActivityType.SCHOOL_VISIT,
            "follow_up_visit": ActivityType.FOLLOW_UP_VISIT,
            "baseline_ssa": ActivityType.BASELINE_SSA_VISIT,
            "cluster_meeting": ActivityType.CLUSTER_MEETING,
            "cluster_training": ActivityType.CLUSTER_TRAINING,
            "core_visit": ActivityType.CORE_VISIT,
            "core_training": ActivityType.CORE_TRAINING,
            "partner_coaching": ActivityType.PARTNER_ACTIVITY,
        }
        activity_type = type_map.get(
            debrief.recommended_next_activity_type, ActivityType.FOLLOW_UP_VISIT
        )
        school_id = debrief.linked_school_ids[0] if debrief.linked_school_ids else None
        # Activity.responsible_staff_id is a User id everywhere else in the
        # app (e.g. my_plan_views.py resolves it via User.objects.get(id=...)),
        # but debrief.staff_id — and, per existing test fixtures, callers'
        # follow_up_owner_id too — is a StaffProfile id (set from
        # _staff_profile(principal).id at submission time). Writing that
        # straight into responsible_staff_id silently orphaned the follow-up
        # Activity from its intended owner's My Plan. Resolve through
        # StaffProfile first; if nothing matches, assume the id was already a
        # User id and pass it through unchanged.
        from apps.accounts.models import StaffProfile

        def _to_user_id(candidate_id):
            if not candidate_id:
                return None
            resolved = (
                StaffProfile.objects.filter(id=candidate_id)
                .values_list("user_id", flat=True)
                .first()
            )
            return resolved or candidate_id

        owner_id = _to_user_id(debrief.follow_up_owner_id) or _to_user_id(
            debrief.staff_id
        )
        # status="planned" (NOT the model default not_planned): the To-Do
        # engine excludes not_planned rows, so the default made an accepted
        # follow-up invisible to its owner. quarter is stamped the same way
        # the catch-up funnel does — an empty quarter hides the draft from
        # every quarter-scoped rollup until someone happens to reschedule it.
        from apps.core.fy import get_quarter_for_date

        activity = Activity.objects.create(
            fy=debrief.fy,
            activity_type=activity_type,
            status="planned",
            quarter=get_quarter_for_date(debrief.follow_up_date),
            responsible_staff_id=owner_id,
            school_id=school_id,
            focus_intervention=debrief.recommended_intervention or None,
            planned_date=debrief.follow_up_date,
            activity_purpose_text=f"Recommended from Field Debrief: {debrief.title}",
        )
        debrief.recommendation_status = RecommendationStatus.ACCEPTED
        debrief.recommendation_accepted_activity_id = activity.id
        debrief.recommendation_reviewed_by_user_id = principal.user_id
        debrief.recommendation_reviewed_at = timezone.now()
        debrief.save(
            update_fields=[
                "recommendation_status",
                "recommendation_accepted_activity_id",
                "recommendation_reviewed_by_user_id",
                "recommendation_reviewed_at",
            ]
        )
        FieldDebriefService._notify_recommendation_review(
            principal, debrief, accepted=True
        )
        FieldDebriefService._notify_follow_up_owner(principal, debrief, activity)
        return activity

    @staticmethod
    def reject_recommendation(principal, debrief_id: str) -> DailyDebrief:
        debrief = FieldDebriefService.get_one(principal, debrief_id)
        if getattr(principal, "active_role", "") not in (
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.ADMIN.value,
        ):
            raise Forbidden("Only a supervisor may reject a debrief recommendation.")
        debrief.recommendation_status = RecommendationStatus.REJECTED
        debrief.recommendation_reviewed_by_user_id = principal.user_id
        debrief.recommendation_reviewed_at = timezone.now()
        debrief.save(
            update_fields=[
                "recommendation_status",
                "recommendation_reviewed_by_user_id",
                "recommendation_reviewed_at",
            ]
        )
        FieldDebriefService._notify_recommendation_review(
            principal, debrief, accepted=False
        )
        return debrief

    @staticmethod
    def _notify_follow_up_owner(principal, debrief: DailyDebrief, activity) -> None:
        """The person who must now schedule the follow-up is not always the
        debrief submitter — without this, an owner who didn't submit the
        debrief had no notification and (pre-fix) no To-Do either, making the
        accepted recommendation undiscoverable."""
        owner = activity.responsible_staff_id
        if not owner or owner in (principal.user_id, debrief.submitted_by_user_id):
            return
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="field_debrief_follow_up_assigned",
            category="field_debrief",
            priority="normal",
            title=f"Follow-up activity assigned: {debrief.title}",
            body=(
                "A field debrief recommendation was accepted and a draft "
                "follow-up activity was created for you to schedule."
            ),
            context_type="activity",
            context_id=activity.id,
            recipients=[owner],
        )

    @staticmethod
    def _notify_recommendation_review(
        principal, debrief: DailyDebrief, *, accepted: bool
    ) -> None:
        """§13 — the submitter learns their recommended follow-up was decided,
        mirroring how the forward direction (routing/clarification) notifies."""
        if (
            not debrief.submitted_by_user_id
            or debrief.submitted_by_user_id == principal.user_id
        ):
            return
        from apps.notifications.services import WorkflowNotificationService

        recommended = (
            debrief.get_recommended_next_activity_type_display() or "follow-up"
        )
        verdict = "accepted — a draft Activity was created" if accepted else "rejected"
        WorkflowNotificationService.trigger(
            event_type="field_debrief_recommendation_reviewed",
            category="field_debrief",
            priority="normal",
            title=f"Recommendation {'accepted' if accepted else 'rejected'}: {debrief.title}",
            body=f"Your recommended {recommended} was {verdict}.",
            context_type="field_debrief",
            context_id=debrief.id,
            recipients=[debrief.submitted_by_user_id],
        )

    @staticmethod
    def resolve_commitment(principal, commitment_id: str) -> DailyDebriefCommitment:
        """§7-G — close the loop on a commitment. Allowed for the debrief's
        submitter (they track the follow-up) or a manager role."""
        commitment = (
            DailyDebriefCommitment.objects.select_related("debrief")
            .filter(id=commitment_id)
            .first()
        )
        if not commitment:
            raise NotFoundError("Commitment not found.")
        FieldDebriefService._assert_can_resolve_child(principal, commitment.debrief)
        if commitment.status == "resolved":
            raise BadRequest("This commitment is already resolved.")
        commitment.status = "resolved"
        commitment.resolved_at = timezone.now()
        commitment.save(update_fields=["status", "resolved_at"])
        return commitment

    @staticmethod
    def resolve_support_request(
        principal, support_request_id: str
    ) -> DailyDebriefSupportRequest:
        """§7-H — close the loop on a support request, recording who resolved it."""
        support_request = (
            DailyDebriefSupportRequest.objects.select_related("debrief")
            .filter(id=support_request_id)
            .first()
        )
        if not support_request:
            raise NotFoundError("Support request not found.")
        FieldDebriefService._assert_can_resolve_child(
            principal, support_request.debrief
        )
        if support_request.status == "resolved":
            raise BadRequest("This support request is already resolved.")
        support_request.status = "resolved"
        support_request.resolved_at = timezone.now()
        support_request.resolved_by_user_id = principal.user_id
        support_request.save(
            update_fields=["status", "resolved_at", "resolved_by_user_id"]
        )
        return support_request

    @staticmethod
    def _assert_can_resolve_child(principal, debrief: DailyDebrief) -> None:
        """Out-of-scope reads stay 404 (never confirm the ID exists); in-scope
        readers still need to be the submitter or a manager to resolve."""
        if not FieldDebriefService.can_read(principal, debrief):
            raise NotFoundError("Debrief not found or not visible to you.")
        role = getattr(principal, "active_role", "")
        if (
            debrief.submitted_by_user_id == principal.user_id
            or role in DEBRIEF_MANAGER_ROLES
        ):
            return
        raise Forbidden(
            "Only the debrief submitter or a manager may resolve this item."
        )


def _users_with_role(role: str, country: str | None = None) -> list[str]:
    """Active users holding `role`, scoped to `country` when given — CD/IA/
    HR/Accountant/RVP each typically have one holder per country/region, so
    an unscoped query would incorrectly notify every country's holder."""
    from apps.accounts.models import User

    qs = User.objects.filter(
        roles__contains=[role], status="active", deleted_at__isnull=True
    )
    if country:
        qs = qs.filter(staff_profile__country=country)
    return list(qs.values_list("id", flat=True))


def _country_staff_ids(country: str | None) -> list[str]:
    from apps.accounts.models import StaffProfile

    if not country:
        return []
    return list(
        StaffProfile.objects.filter(country=country).values_list("id", flat=True)
    )


def _school_ids_in_district(district_id: str) -> list[str]:
    from apps.schools.models import School

    return list(
        School.objects.filter(district_id=district_id).values_list("id", flat=True)
    )
