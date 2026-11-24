package coreforms

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// AssignPartnerRefused is the view's answer to a role that may not assign.
const AssignPartnerRefused = "Access Denied: You do not have permission to assign to partner."

// Withdrawal is _prior_withdrawals' newest row the drawer warns of.
type Withdrawal struct{ Partner, Reason string }

// ClientAssignForm is assign_partner_modal_view's context for one school.
type ClientAssignForm struct {
	School           School
	Partners         []Partner
	Courses          []Course
	FollowUps        []FollowUp
	FollowUpRequired bool
	FY               string
	Handovers        []projectcapacity.HandoverRoute
	Purposes         []PurposeChoice
	// Notes are the lock reasons (each once, in the purposes' order) and the
	// on-top training note.
	Notes      []string
	Withdrawal *Withdrawal
	Today      string
	Monitor    string
}

// withdrawalReasons is WithdrawalReason's labels.
var withdrawalReasons = map[string]string{
	"not_scheduled": "Partner has not scheduled", "scheduling_delay": "Repeated scheduling delay",
	"repeated_reschedule": "Repeated rescheduling", "capacity": "Partner capacity constraint",
	"partner_unavailable": "Partner unavailable", "poor_quality": "Poor quality of work",
	"poor_evidence": "Poor evidence quality", "repeated_evidence_return": "Repeated evidence return",
	"communication": "Communication breakdown", "missed_deadline": "Missed activity deadline",
	"conduct": "Conduct or integrity concern", "safeguarding": "Safeguarding concern",
	"partner_requested_release": "Partner requested release", "school_unavailable": "School unavailable",
	"school_complaint": "School complaint", "school_requested_change": "School requested a change",
	"out_of_scope": "Assignment outside partner scope", "incorrect_assignment": "Incorrect school or activity",
	"duplicate_assignment": "Duplicate assignment", "support_not_required": "Support no longer required",
	"programme_change": "Project or programme change", "strategic_reallocation": "Strategic reallocation",
	"distance": "Distance or travel constraint", "safety": "Safety or access concern",
	"other": "Other documented reason",
}

// ClientAssignFor is assign_partner_modal_view for a school.
func (s *Service) ClientAssignFor(ctx context.Context, p auth.Principal, code string, interventions [][2]string) (ClientAssignForm, error) {
	if !MayAssign(p.ActiveRole) {
		return ClientAssignForm{}, &Refusal{Message: AssignPartnerRefused}
	}
	// Q(id=school_id) | Q(school_id=school_id): the drawer may name either.
	keyed, err := s.schoolByKey(ctx, code)
	if err != nil {
		return ClientAssignForm{}, err
	}
	school, err := s.Operational(ctx, p, keyed.Code)
	if err != nil {
		return ClientAssignForm{}, err
	}
	fy := schooldirectory.OperationalFY(s.now())
	gate, err := s.gateOf(ctx, school, fy)
	if err != nil {
		return ClientAssignForm{}, err
	}
	if !gate.CanAssignPartner {
		return ClientAssignForm{}, &Refusal{Message: gate.AssignReason}
	}
	names := namesOf(interventions)
	form := ClientAssignForm{School: school, FY: fy, Today: s.localDay().Format("2 Jan 2006"), Monitor: p.Name}
	if form.Monitor == "" {
		form.Monitor = "You"
	}
	if form.Partners, err = s.assignablePartners(ctx); err != nil {
		return ClientAssignForm{}, err
	}
	all, err := s.courses(ctx, names, s.localDay())
	if err != nil {
		return ClientAssignForm{}, err
	}
	for _, course := range all {
		if course.PartnerAllowed {
			form.Courses = append(form.Courses, course)
		}
	}
	locks := map[string]string{}
	onTop := ""
	if gate.OneCommitment(s.gates) && !gate.CanAssignVisit {
		locks["training_follow_up"] = gate.AssignVisitReason
		var universal []Course
		for _, course := range form.Courses {
			if course.Universal {
				universal = append(universal, course)
			}
		}
		if len(universal) > 0 {
			form.Courses = universal
			labels := make([]string, len(universal))
			for i, course := range universal {
				labels[i] = course.Label
			}
			onTop = "An In-school Training can still be assigned for " + strings.Join(labels, ", ") +
				", which every school takes on top of its year."
		} else {
			locks["in_school_training"] = gate.AssignVisitReason
		}
	}
	if !gate.CanAssignSSA {
		locks["ssa_support"] = gate.AssignSSAReason
	}
	for _, purpose := range partnerPurposes {
		choice := PurposeChoice{Value: purpose.Value, Label: purpose.Label}
		if _, locked := locks[purpose.Value]; locked {
			choice.Label += " — not available"
			choice.Disabled = true
		}
		form.Purposes = append(form.Purposes, choice)
	}
	// list(dict.fromkeys(purpose_locks.values())): the dict's insertion order.
	for _, key := range []string{"training_follow_up", "in_school_training", "ssa_support"} {
		if reason, ok := locks[key]; ok && !slices.Contains(form.Notes, reason) {
			form.Notes = append(form.Notes, reason)
		}
	}
	if onTop != "" {
		form.Notes = append(form.Notes, onTop)
	}
	if form.FollowUps, err = s.followUps(ctx, school, fy, names, schoolprofile.ActivityTypeLabels()); err != nil {
		return ClientAssignForm{}, err
	}
	if form.FollowUpRequired, err = activities.FollowUpNeedsTraining(ctx, s.db, p.Country, fy); err != nil {
		return ClientAssignForm{}, fmt.Errorf("coreforms: reading the year's follow-up rule: %w", err)
	}
	if form.Withdrawal, err = s.priorWithdrawal(ctx, school.ID); err != nil {
		return ClientAssignForm{}, err
	}
	if form.Handovers, err = s.handovers(ctx, p, school); err != nil {
		return ClientAssignForm{}, err
	}
	return form, nil
}

// priorWithdrawal is _prior_withdrawals(school)[0]: the newest withdrawal not
// rejected or cancelled.
func (s *Service) priorWithdrawal(ctx context.Context, schoolID string) (*Withdrawal, error) {
	var w Withdrawal
	var reason string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(p.name, ''), COALESCE(w.reason_category, '')
  FROM partner_assignment_withdrawal w LEFT JOIN partner p ON p.id = w.partner_id
 WHERE w.school_id = $1 AND w.state NOT IN ('rejected', 'cancelled') ORDER BY w.requested_at DESC LIMIT 1`, schoolID).Scan(&w.Partner, &reason)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the school's withdrawals: %w", err)
	}
	w.Reason = reason
	if label, ok := withdrawalReasons[reason]; ok {
		w.Reason = label
	}
	return &w, nil
}
