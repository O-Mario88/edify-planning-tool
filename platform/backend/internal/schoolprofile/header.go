package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// header is pages/schools/detail.html's header for an open school: back to
// the directory, the name and School ID, the readiness, SSA and visit-lock
// badges, and the doors the reader may use.
func (s *Service) header(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, sc school, now time.Time) (*screensv1.PageHeader, error) {
	d := rules.Doors[p.ActiveRole]
	h := &screensv1.PageHeader{
		BackLabel:   "Back to School Directory",
		BackHref:    "/schools",
		Title:       sc.Name,
		Description: "School ID: " + sc.SchoolID,
		Badges:      []*screensv1.PageBadge{readinessBadge(sc)},
		Actions:     []*screensv1.PageAction{},
	}
	closed := sc.closed()
	if closed {
		// A closed school is reached from the Closed Schools archive, takes
		// no new work, and has no visit of the year to lock.
		h.BackLabel, h.BackHref = "Back to Closed Schools", "/schools/closed"
	}

	// Enter SSA Score and the year's SSA (ssa.creation.entry_state).
	fy := localFY(now)
	record, err := s.yearRecord(ctx, sc.ID, fy)
	if err != nil {
		return nil, err
	}
	entryShown := false
	if d.EnterSSA && !closed {
		if entryShown, err = schooldirectory.InReach(ctx, s.db, scope, sc.ID); err != nil {
			return nil, err
		}
	}
	switch {
	case record != nil:
		h.Badges = append(h.Badges, record.badge(fy))
	case entryShown:
		h.Badges = append(h.Badges, &screensv1.PageBadge{Text: "No FY" + fy + " SSA", Tone: "plain"})
	}

	// The year's support visit (_profile_planning_controls, visit_gate).
	var gate visitgate.Gate
	if !closed {
		operational := schooldirectory.OperationalFY(now)
		gate, err = visitgate.Of(ctx, s.db, rules.Gate,
			visitgate.School{ID: sc.ID, Code: sc.SchoolID, Name: sc.Name, Type: sc.Type}, operational, operational)
		if err != nil {
			return nil, err
		}
		if lock := gate.LockLabel(rules.Gate); lock != "" {
			h.Badges = append(h.Badges, &screensv1.PageBadge{Text: lock, Tone: "plain", Title: gate.StaffReason, Icon: "lock"})
		}
	}

	h.Actions = append(h.Actions, drawer("Edit Details", "/schools/"+sc.ID+"/edit-drawer", true))
	// A Core school's doors are the Core Schools drawers, for a reader of
	// that page (profile_core_routes).
	schedule, assign := "/planning/schedule-modal?school_id=", "/planning/assign-partner-modal?school_id="
	if sc.Type == "core" && d.CoreSchools {
		schedule, assign = "/core-schools/schedule-activity?school_id=", "/core-schools/assign-partner?school_id="
	}
	if d.Schedule && !closed {
		// A staff support visit locks only a closed school's Schedule, and a
		// closed school is not served here.
		h.Actions = append(h.Actions, drawer("Schedule", schedule+sc.SchoolID, false))
	}
	if d.AssignPartner && !closed {
		if gate.CanAssignPartner {
			h.Actions = append(h.Actions, drawer("Assign to Partner", assign+sc.SchoolID, false))
		} else {
			h.Actions = append(h.Actions, greyed("Assign to Partner", gate.AssignReason))
		}
	}
	if entryShown {
		if record != nil {
			h.Actions = append(h.Actions, greyed("Enter SSA Score", "SSA already entered for FY"+fy))
		} else {
			h.Actions = append(h.Actions, drawer("Enter SSA Score", "/schools/"+sc.ID+"/ssa-entry", false))
		}
	}
	if d.AssignProject {
		h.Actions = append(h.Actions, drawer("Add to Project", "/schools/"+sc.ID+"/assign-to-project", false))
	}
	if d.TransferOwner {
		h.Actions = append(h.Actions, drawer("Reassign Owner", "/schools/"+sc.SchoolID+"/transfer-owner", false))
	}
	if !closed {
		h.Actions = append(h.Actions, drawer("Close School", "/schools/"+sc.SchoolID+"/close-drawer", false))
	}
	return h, nil
}

// readinessBadge: the page colours "ready" and "limited", values the
// readiness never holds, so the badge reads plain.
func readinessBadge(sc school) *screensv1.PageBadge {
	tone := "plain"
	switch sc.Readiness {
	case "ready":
		tone = "good"
	case "limited":
		tone = "caution"
	}
	return &screensv1.PageBadge{Text: "Readiness: " + label(rules.Readiness, sc.Readiness), Tone: tone}
}

// drawer is a header button that opens a drawer; its key is the page
// blocks' slug of its label.
func drawer(text, href string, primary bool) *screensv1.PageAction {
	return &screensv1.PageAction{Key: slug(text), Label: text, Primary: primary, Enabled: true, Href: href, Drawer: true}
}

// greyed is a door the rules close here, kept with its reason.
func greyed(text, reason string) *screensv1.PageAction {
	return &screensv1.PageAction{Key: slug(text), Label: text, Reason: reason}
}

// slug is page_blocks._slug.
func slug(text string) string {
	out := []byte{}
	gap := false
	for _, c := range []byte(text) {
		switch {
		case c >= 'A' && c <= 'Z':
			c += 'a' - 'A'
			fallthrough
		case (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'):
			if gap && len(out) > 0 {
				out = append(out, '_')
			}
			gap = false
			out = append(out, c)
		default:
			gap = true
		}
	}
	return string(out)
}

// ssaRecord is the record holding a school's year (ssa.creation.year_record).
type ssaRecord struct {
	average        *float64
	status, source string
	onVisit        bool
}

// yearRecord is the pending or confirmed record of the year, the confirmed
// one first, then the latest.
func (s *Service) yearRecord(ctx context.Context, schoolID, fy string) (*ssaRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT average_score, verification_status, COALESCE(verification_source, ''), COALESCE(source_activity_id, '') <> ''
FROM ssa_record WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL AND verification_status = ANY($3)
ORDER BY date_of_ssa DESC`, schoolID, fy, rules.SSAHoldingStatuses)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the year's SSA: %w", err)
	}
	records, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (ssaRecord, error) {
		var r ssaRecord
		err := row.Scan(&r.average, &r.status, &r.source, &r.onVisit)
		return r, err
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, fmt.Errorf("schoolprofile: reading the year's SSA: %w", err)
	}
	slices.SortStableFunc(records, func(a, b ssaRecord) int {
		return boolRank(a.status != "confirmed") - boolRank(b.status != "confirmed")
	})
	if len(records) == 0 {
		return nil, nil
	}
	return &records[0], nil
}

func boolRank(b bool) int {
	if b {
		return 1
	}
	return 0
}

// sourceLabel is ssa.creation.source_label.
func (r ssaRecord) sourceLabel() string {
	if r.source == rules.SSASourceStaffKeyed && r.onVisit {
		return rules.SSASourceOnVisit
	}
	if l, ok := rules.SSASources[r.source]; ok {
		return l
	}
	return rules.SSASourceOther
}

// badge is the header's "SSA FY2027: 6.2", with the record's status where
// it is not confirmed yet.
func (r ssaRecord) badge(fy string) *screensv1.PageBadge {
	average := "—"
	if r.average != nil && *r.average != 0 {
		average = pyFloat(*r.average)
	}
	status := label(rules.SSAStatuses, r.status)
	text := "SSA FY" + fy + ": " + average
	tone := "good"
	if r.status != "confirmed" {
		text += " · " + status
		tone = "plain"
	}
	return &screensv1.PageBadge{Text: text, Tone: tone, Title: "Source: " + r.sourceLabel() + " · " + status}
}

// closedBanner is a closed school's banner above every tab: its status and
// the day it stopped, and the latest closure's reason and what it took. The
// page's reopening form is not read.
func (s *Service) closedBanner(ctx context.Context, sc school) (*screensv1.PageBlock, error) {
	first := label(rules.OperationalStatuses, sc.Status)
	if sc.ClosureDate != nil {
		first += " · " + jMY(*sc.ClosureDate)
	}
	items := []*screensv1.PagePanelItem{text(collapse(first))}
	var reasonCategory, reason string
	var enrolment *int32
	var cancelled int32
	err := s.db.QueryRow(ctx, `
SELECT COALESCE(reason_category, ''), COALESCE(reason, ''), enrollment_at_closure, COALESCE(activities_cancelled, 0)
FROM school_closure WHERE school_id = $1 ORDER BY effective_date DESC, created_at DESC LIMIT 1`, sc.ID).Scan(
		&reasonCategory, &reason, &enrolment, &cancelled)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
	case err != nil:
		return nil, fmt.Errorf("schoolprofile: reading the closure: %w", err)
	default:
		items = append(items, text(collapse(label(rules.ClosureReasons, reasonCategory)+" — "+reason)))
		took := ""
		if enrolment != nil && *enrolment != 0 {
			took += intcomma(int(*enrolment)) + " learners at closure · "
		}
		if cancelled != 0 {
			took += fmt.Sprintf("%d future activity(s) cancelled · ", cancelled)
		}
		items = append(items, text(took+"History, evidence, finance and target credit are unchanged."))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Badges: []*screensv1.PageBadge{}, Items: pairedItems(items)}}}, nil
}
