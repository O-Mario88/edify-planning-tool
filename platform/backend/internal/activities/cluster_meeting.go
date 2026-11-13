package activities

// The eighth save (docs/migration/49): a cluster meeting, planned from
// Planning's Schedule drawer for a cluster
// (/planning/schedule-modal?cluster_id=…&action=meeting, posting to
// /planning/schedule-action): schedule_action_view's cluster branch with
// activity_type cluster_meeting, then activities.services._create for a
// cluster, then cluster_attendance.set_invited_schools — the Group
// Training's path (docs/migration/38) with the meeting's own item, kind and
// focus, and the "added to my plan" audit row.
//
// Go takes the owner's own staff meeting that is not a training (Only
// Meeting or Cluster Leaders Meeting) at a cluster they are responsible
// for, its item the standard Cluster Meeting the view resolves, per school
// by category, the schools ticked by name and none of them a Core school,
// Facilitated by Staff, on a day the pricing pools. A Training meeting (a
// course and a ceiling), no school ticked (the whole cluster), a partner
// facilitating and everything else is handed on unchanged.

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

const (
	// schedule_action_view 2112–2118 and _create 2284–2288.
	unknownMeetingKind = "Choose the meeting type: Training, Only Meeting or Cluster Leaders Meeting."
	// schedule_action_view 2276–2286.
	noMeetingItem = "No single approved Activity Catalogue item costs this cluster activity. Ask the Country Director to configure it."
	// The drawer's hidden purpose_type for a meeting
	// (partials/planning/schedule_cluster_drawer.html 127).
	meetingPurposeType = "operational_admin"
	// _notify_scheduled_owner's audit action (services.py 3633).
	meetingAddedAction = "activity.cluster_meeting_added_to_my_plan"
)

// ClusterMeetingRequest is the cluster drawer's fields for a meeting.
type ClusterMeetingRequest struct {
	GroupTrainingRequest
	// The meeting type as posted, the focus the planner chose (blank:
	// none) and the drawer's purpose type.
	MeetingKind, Focus, PurposeType string
}

// meetingFormFields are the fields the meeting drawer posts for this case.
// Any other field carrying a value (a course for a Training meeting, a
// school, a responsible person, online delivery, a priority, a catalogue
// item) names a case Go does not take, and the request is handed on whole.
var meetingFormFields = func() map[string]bool {
	out := map[string]bool{"meeting_kind": true, "focus_intervention": true, "purpose_type": true}
	for name := range groupFormFields {
		if name != "catalogue_item_id" {
			out[name] = true
		}
	}
	return out
}()

// IsClusterMeetingForm is whether the posted form is a cluster's meeting.
func IsClusterMeetingForm(form url.Values) bool {
	return strings.TrimSpace(form.Get("cluster_id")) != "" && form.Get("activity_type") == rules.ClusterMeeting.ActivityType
}

// ClusterMeetingRequestFromForm reads the drawer's form; false when Go does
// not take it.
func ClusterMeetingRequestFromForm(form url.Values) (ClusterMeetingRequest, bool) {
	if !IsClusterMeetingForm(form) {
		return ClusterMeetingRequest{}, false
	}
	for name, values := range form {
		if meetingFormFields[name] {
			continue
		}
		for _, v := range values {
			if strings.TrimSpace(v) != "" {
				return ClusterMeetingRequest{}, false
			}
		}
	}
	// The training's reader takes the shared fields; it hands on what it
	// hands on for a training too (a partner facilitating, no "Facilitated
	// by", another delivery).
	shared := url.Values{}
	for name, values := range form {
		if groupFormFields[name] {
			shared[name] = values
		}
	}
	shared.Set("activity_type", rules.GroupTraining.ActivityType)
	base, ok := GroupTrainingRequestFromForm(shared)
	if !ok {
		return ClusterMeetingRequest{}, false
	}
	return ClusterMeetingRequest{
		GroupTrainingRequest: base,
		MeetingKind:          strings.TrimSpace(form.Get("meeting_kind")),
		Focus:                strings.TrimSpace(form.Get("focus_intervention")),
		PurposeType:          form.Get("purpose_type"),
	}, true
}

// ScheduleClusterMeeting makes the save, or refuses it in the existing
// words, or hands it on (ErrHandOn).
func (s *Service) ScheduleClusterMeeting(ctx context.Context, p auth.Principal, req ClusterMeetingRequest, origin Origin) (Answer, error) {
	gp, err := s.prepareMeeting(ctx, p, req, origin)
	if err != nil {
		return Answer{}, err
	}
	rowID, err := s.writeGroup(ctx, gp)
	if err != nil {
		return Answer{}, err
	}
	s.afterCommit(ctx, gp.plan, rowID)
	answer, err := s.answer(ctx, gp.plan)
	if err != nil {
		return Answer{}, err
	}
	answer.Message = groupScheduledMessage
	return answer, nil
}

// prepareMeeting is the view's cluster branch for a meeting, then
// `_create` up to its transaction (createGroup, shared with the training).
func (s *Service) prepareMeeting(ctx context.Context, p auth.Principal, req ClusterMeetingRequest, origin Origin) (*groupPlan, error) {
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	g := rules.GroupTraining
	// The drawer's gate (1987).
	if !in(rules.Doors.Drawer, p.ActiveRole) {
		message := noPermission
		if p.ActiveRole == rules.Doors.AdminRole {
			message = rules.Doors.AdminRefusal
		}
		return nil, &Refusal{Message: message, Forbidden: true}
	}
	if in(rules.Doors.Requesters, p.ActiveRole) || p.InActingAppointment || p.StaffProfileID == "" ||
		in(g.CountryRoles, p.ActiveRole) || in(g.VisitOnlyRoles, p.ActiveRole) || in(g.SummaryRoles, p.ActiveRole) ||
		(req.Date != "" && !isoDate.MatchString(req.Date)) || req.ClusterID == "" {
		return nil, handOn("not the owner's own cluster meeting")
	}
	// The date (2061–2072).
	if req.Date == "" {
		return nil, refuse("Pick the date this is planned for before scheduling it.")
	}
	day, err := time.ParseInLocation(time.DateOnly, req.Date, s.kampala)
	if err != nil {
		return nil, refuse("That scheduled date is not a valid calendar date.")
	}
	ss, err := meetingSession(req)
	if err != nil {
		return nil, err
	}
	// The schools ticked (2396–2415): none ticked invites the whole cluster.
	if !req.InvitedShown || len(req.Invited) == 0 {
		return nil, handOn("no school ticked: the whole cluster is invited")
	}
	if hasDuplicate(req.Invited) {
		return nil, handOn("a school ticked twice")
	}
	// The meeting's item (2276–2287), resolved on today as the view does.
	it, err := resolveForKind(ctx, s.db, ss.activityType, today)
	if err != nil {
		return nil, err
	}
	if it == nil {
		return nil, refuse(noMeetingItem)
	}
	ss.itemID = it.ID
	cl, err := clusterOf(ctx, s.db, req.ClusterID)
	if err != nil {
		return nil, err
	}
	if cl == nil {
		return nil, handOn("an unknown or removed cluster")
	}
	return s.createGroup(ctx, p, req.GroupTrainingRequest, origin, now, today, day, *cl, ss)
}

// meetingSession is the meeting's kind and focus as the view and `_create`
// read them (2106–2141, 2281–2292): an unknown kind is refused; a Training
// meeting, a blank kind, a focus that is not an SSA intervention or another
// purpose type is handed on.
func meetingSession(req ClusterMeetingRequest) (session, error) {
	m := rules.ClusterMeeting
	if req.MeetingKind != "" && !in(m.MeetingKinds, req.MeetingKind) {
		return session{}, refuse(unknownMeetingKind)
	}
	if req.MeetingKind == "" || req.MeetingKind == m.TrainingKind {
		return session{}, handOn("a Training meeting or no meeting type")
	}
	if req.PurposeType != meetingPurposeType {
		return session{}, handOn("a purpose type the meeting drawer does not post")
	}
	if req.Focus != "" && rules.labels[req.Focus] == "" {
		return session{}, handOn("a focus that is not an SSA intervention")
	}
	return session{activityType: m.ActivityType, purpose: meetingPurposeType, meetingKind: req.MeetingKind,
		focus: req.Focus}, nil
}

// auditMeetingAdded is the audit row _notify_scheduled_owner appends for a
// cluster meeting after `activity.scheduled` (services.py 3631–3646): the
// owner, the year and the My Plan week it sits in.
func (s *Service) auditMeetingAdded(ctx context.Context, pl *plan) error {
	r := pl.row
	if !in(rules.ClusterMeeting.MeetingTypes, r.activityType) {
		return nil
	}
	day := r.plannedDate
	payload := map[string]any{
		"owner": r.responsible, "monitoredBy": nil, "partner": nil, "fy": r.fy,
		"plannedDate": day.Format(time.DateOnly), "myPlanWeek": min(5, (day.Day()-1)/7+1),
	}
	role := pl.p.ActiveRole
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, s.now())
	if err != nil {
		return err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: meetingAddedAction, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(r.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true, Payload: withStamps(payload, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return fmt.Errorf("activities: appending the meeting's audit row: %w", err)
	}
	return tx.Commit(ctx)
}
