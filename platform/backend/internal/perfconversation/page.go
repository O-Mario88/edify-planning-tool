// Package perfconversation is the Performance Conversation
// (/performance-conversation, hr_views.performance_conversation_view,
// pages/hr/performance_conversation.html): one employee's annual agreement
// for the operational year, opened by the employee, their reviewer (or
// whoever covers the reviewer), their functional manager or HR, with a
// column of the form each of them writes, the distributed priorities and the
// Edify values the conversation is held against.
//
// Go builds the page for the agreement as it stands: no agreement, the
// window shut, or the window open over reflective priorities. It hands on
// a reader the page refuses (the existing page redirects), a reader in an
// acting appointment, and, in an open window, a conversation frozen by its
// snapshot, a measured priority (its live figures and milestones), an
// inherited priority carried under a role rule, or a contract longer than
// one page. Every save stays with the existing application.
//
// The rules are exported to rules.json by `manage.py
// export_perf_conversation_rules`; apps/hr/test_perf_conversation_rules_export.py
// fails when the two differ.
package perfconversation

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/performance-conversation"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles         map[string]bool     `json:"roles"`
	WindowLabels  map[string]string   `json:"window_labels"`
	Ratings       [][2]string         `json:"ratings"`
	ValueKinds    map[string]string   `json:"value_kinds"`
	ReviewerRoles map[string][]string `json:"reviewer_roles"`
	LiveStates    []string            `json:"live_states"`
	HRRoles       []string            `json:"hr_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.WindowLabels) == 0 || len(r.Ratings) == 0 ||
		len(r.ValueKinds) == 0 || len(r.ReviewerRoles) == 0 || len(r.LiveStates) == 0 || len(r.HRRoles) == 0 {
		panic(fmt.Sprintf("perfconversation: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("perfconversation: " + err.Error())
	}
	return z
}()

// person is a People record and its account.
type person struct {
	id, userID, name, role string
	title                  *string
}

// conversation is _resolve_conversation's answer: the review, the person it
// is about and the channels the reader writes.
type conversation struct {
	target   person
	reviewID string
	fy       string
	stage    string
	caps     map[string]bool
}

// errHandOn passes the reader on to the existing page.
var errHandOn = errors.New("perfconversation: handed on")

// Build answers the page, or passes the reader on (served false).
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !rules.Roles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.InActingAppointment {
		return nil, false, nil
	}
	resp, err := s.page(ctx, p, query)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

func (s *Service) page(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, error) {
	now := s.now()
	c, err := s.resolve(ctx, p, strings.TrimSpace(query.Get("staff")), now)
	if err != nil {
		return nil, err
	}
	window := "none"
	if c.reviewID != "" {
		err := s.db.QueryRow(ctx, `SELECT active_window FROM hr_performance_cycle WHERE fy = $1 ORDER BY id LIMIT 1`, c.fy).Scan(&window)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("perfconversation: reading the cycle: %w", err)
		}
	}
	open := c.reviewID != "" && window != "none"
	label, ok := rules.WindowLabels[window]
	if !ok {
		label = "No window open"
	}
	description := c.target.name
	if c.target.title != nil && *c.target.title != "" {
		description += " · " + *c.target.title
	}
	header := &screensv1.PageHeader{Eyebrow: "People & Culture", Title: label,
		Description: collapse(description + " — reflections and ratings are entered here; the numbers are frozen from the snapshot.")}
	if c.caps["manager"] && p.ActiveRole == "Program Lead" {
		header.Actions = []*screensv1.PageAction{{Key: "performance_reviews", Label: "Performance Reviews", Enabled: true, Href: "/performance-reviews"}}
	}
	blocks := []*screensv1.PageBlock{}
	var priorities []priority
	if c.reviewID != "" {
		if priorities, err = s.priorities(ctx, c.reviewID); err != nil {
			return nil, err
		}
	}
	if c.reviewID != "" && c.caps["manager"] && c.stage == "priorities_manager_review" {
		blocks = feedOf(blocks, agreementCard(c, priorities))
	}
	switch {
	case c.reviewID == "":
		blocks = feedOf(blocks, notice("No performance agreement exists for this person yet.",
			"HR opens the cycle and the draft agreement is generated first."))
	case !open:
		blocks = feedOf(blocks, notice("The performance form is locked.",
			"A conversation can only be completed inside an HR-activated window."))
	default:
		more, err := s.openForm(ctx, c, window, priorities, now)
		if err != nil {
			return nil, err
		}
		blocks = append(blocks, more...)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}, nil
}

// openForm is the conversation in an open window: the distributed summary,
// a card a priority, the values and the sign-off.
func (s *Service) openForm(ctx context.Context, c conversation, window string, priorities []priority, now time.Time) ([]*screensv1.PageBlock, error) {
	var frozen bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM hr_performance_snapshot WHERE review_id = $1 AND "window" = $2)`,
		c.reviewID, window).Scan(&frozen); err != nil {
		return nil, fmt.Errorf("perfconversation: reading the snapshot: %w", err)
	}
	if frozen {
		return nil, errHandOn
	}
	for _, pr := range priorities {
		if pr.metricKey != "" || (pr.mandatory && pr.ruled) {
			return nil, errHandOn
		}
	}
	local := now.In(zone)
	contract, err := allocations.Read(ctx, s.db, auth.Principal{Account: auth.Account{
		UserID: c.target.userID, ActiveRole: c.target.role, StaffProfileID: c.target.id}},
		c.fy, now, time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC))
	if err != nil {
		return nil, err
	}
	if len(contract.Rows) > allocations.SummaryRows {
		return nil, errHandOn
	}
	blocks := allocations.SummaryBlocks(contract)
	for _, pr := range priorities {
		blocks = feedOf(blocks, priorityCard(pr, c.caps))
	}
	values, err := s.commitments(ctx, c.reviewID)
	if err != nil {
		return nil, err
	}
	if len(values) > 0 {
		blocks = feedOf(blocks, valuesCard(values, c.caps))
	}
	return feedOf(blocks, signOffCard()), nil
}

// resolve is _resolve_conversation: whose conversation the reader opens
// (their own, or with ?staff= someone in their People reach or whose
// reviewer they cover) and the channels they write. A reader with no
// People record, or none of the channels, is refused: handed on.
func (s *Service) resolve(ctx context.Context, p auth.Principal, staff string, now time.Time) (conversation, error) {
	var viewer *string
	err := s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1`, p.UserID).Scan(&viewer)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return conversation{}, fmt.Errorf("perfconversation: reading the reader: %w", err)
	}
	viewerID := ""
	if viewer != nil {
		viewerID = *viewer
	}
	var target *person
	if staff != "" && staff != viewerID {
		where, args, _, err := hrregister.PeopleReachProfiles(ctx, s.db, p, []any{staff})
		if err != nil {
			return conversation{}, err
		}
		if target, err = s.person(ctx, `sp.id = $1 AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND `+where, args...); err != nil {
			return conversation{}, err
		}
		if target == nil && viewerID != "" {
			candidate, err := s.person(ctx, `sp.id = $1 AND sp.deleted_at IS NULL`, staff)
			if err != nil {
				return conversation{}, err
			}
			if candidate != nil {
				reviews, err := s.reviews(ctx, *candidate, viewerID, now)
				if err != nil {
					return conversation{}, err
				}
				if reviews {
					target = candidate
				}
			}
		}
	} else if viewerID != "" {
		if target, err = s.person(ctx, `sp.id = $1`, viewerID); err != nil {
			return conversation{}, err
		}
	}
	if target == nil {
		return conversation{}, errHandOn
	}
	c := conversation{target: *target, caps: map[string]bool{}, fy: schooldirectory.OperationalFY(now.UTC())}
	if viewerID != "" && target.id == viewerID {
		c.caps["employee"] = true
	}
	if viewerID != "" && target.id != viewerID {
		reviews, err := s.reviews(ctx, *target, viewerID, now)
		if err != nil {
			return conversation{}, err
		}
		c.caps["manager"] = reviews
	}
	var functional *string
	err = s.db.QueryRow(ctx, `
SELECT id, stage, functional_manager_id FROM hr_performance_review
WHERE staff_id = $1 AND fy = $2 AND review_type = 'annual_priorities' ORDER BY id LIMIT 1`, target.id, c.fy).
		Scan(&c.reviewID, &c.stage, &functional)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return conversation{}, fmt.Errorf("perfconversation: reading the review: %w", err)
	}
	if c.reviewID != "" && functional != nil && *functional == p.UserID {
		c.caps["functional"] = true
	}
	if slices.Contains(rules.HRRoles, p.ActiveRole) {
		c.caps["hr"] = true
	}
	if !c.caps["employee"] && !c.caps["manager"] && !c.caps["functional"] && !c.caps["hr"] {
		return conversation{}, errHandOn
	}
	return c, nil
}

// person reads the People record a WHERE clause on staff_profile `sp` and
// "user" `u` names, or nil.
func (s *Service) person(ctx context.Context, where string, args ...any) (*person, error) {
	var t person
	err := s.db.QueryRow(ctx, `SELECT sp.id, u.id, COALESCE(u.name, ''), COALESCE(u.active_role, ''), sp.title
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE `+where+` ORDER BY sp.id LIMIT 1`, args...).
		Scan(&t.id, &t.userID, &t.name, &t.role, &t.title)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("perfconversation: reading the person: %w", err)
	}
	return &t, nil
}

// reviews is review_authority.is_reviewer_of: whether the reader (their
// People record) is the person's resolved reviewer, a live supervisor in the
// role the person is reviewed by, or covers one of them now.
func (s *Service) reviews(ctx context.Context, target person, viewerID string, now time.Time) (bool, error) {
	if viewerID == target.id {
		return false, nil
	}
	expected := rules.ReviewerRoles[target.role]
	if len(expected) == 0 {
		return false, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id IN (SELECT supervisor_id FROM staff_supervisor_assignment WHERE supervisee_id = $1)
  AND u.active_role = ANY($2) AND u.is_active AND u.deleted_at IS NULL AND sp.deleted_at IS NULL
  AND sp.onboarding_state = ANY($3)`, target.id, expected, rules.LiveStates)
	if err != nil {
		return false, fmt.Errorf("perfconversation: reading the reviewers: %w", err)
	}
	reviewers, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return false, fmt.Errorf("perfconversation: reading the reviewers: %w", err)
	}
	if len(reviewers) == 0 {
		return false, nil
	}
	if slices.Contains(reviewers, viewerID) {
		return true, nil
	}
	var covering bool
	err = s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM temporary_coverage_assignment
  WHERE original_staff_id = ANY($1) AND status = 'active' AND start_datetime <= $2 AND end_datetime >= $2 AND covering_staff_id = $3)`,
		reviewers, now, viewerID).Scan(&covering)
	if err != nil {
		return false, fmt.Errorf("perfconversation: reading the cover: %w", err)
	}
	return covering, nil
}

// priority is one priority of the agreement.
type priority struct {
	id, outcome, metricKey            string
	sequence, weight                  int
	alignment                         *string
	reflection, employeeRating        *string
	assessment, managerRating, action *string
	functionalRating                  *string
	mandatory, ruled                  bool
}

func (s *Service) priorities(ctx context.Context, reviewID string) ([]priority, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, sequence, outcome_statement, strategic_alignment, weight, COALESCE(metric_key, ''), employee_reflection, employee_rating,
       manager_assessment, manager_rating, agreed_action, functional_manager_rating, is_mandatory, source_rule_id IS NOT NULL
FROM hr_performance_priority WHERE review_id = $1 ORDER BY sequence`, reviewID)
	if err != nil {
		return nil, fmt.Errorf("perfconversation: reading the priorities: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (priority, error) {
		var pr priority
		err := r.Scan(&pr.id, &pr.sequence, &pr.outcome, &pr.alignment, &pr.weight, &pr.metricKey, &pr.reflection, &pr.employeeRating,
			&pr.assessment, &pr.managerRating, &pr.action, &pr.functionalRating, &pr.mandatory, &pr.ruled)
		return pr, err
	})
}

// commitment is one value or spiritual commitment.
type commitment struct {
	id, name, kind                  string
	behaviour, reflection, evidence *string
}

// commitments are the review's values, then its spiritual commitments, each
// as the existing queryset reads them (no order of their own).
func (s *Service) commitments(ctx context.Context, reviewID string) ([]commitment, error) {
	out := []commitment{}
	for _, kind := range []string{"value", "spiritual"} {
		rows, err := s.db.Query(ctx, `
SELECT id, value_name, kind, agreed_behaviour, employee_reflection, manager_evidence
FROM hr_value_commitment WHERE review_id = $1 AND kind = $2`, reviewID, kind)
		if err != nil {
			return nil, fmt.Errorf("perfconversation: reading the commitments: %w", err)
		}
		list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (commitment, error) {
			var c commitment
			err := r.Scan(&c.id, &c.name, &c.kind, &c.behaviour, &c.reflection, &c.evidence)
			return c, err
		})
		if err != nil {
			return nil, fmt.Errorf("perfconversation: reading the commitments: %w", err)
		}
		out = append(out, list...)
	}
	return out, nil
}

func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }
