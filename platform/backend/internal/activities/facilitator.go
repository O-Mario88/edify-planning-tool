package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
)

// Who facilitates a planned training or meeting (my_plan_views.
// facilitator_drawer_view and services.set_facilitator), with Django absent.
// A change that re-prices the work is Go's only where the work shares its
// day: its day is priced again through the costs to follow, as a schedule
// is. Work priced on its own, online or as the free half of a pair is
// handed on.

// FacilitatorSaved is the saved_in_place answer.
const FacilitatorSaved = "Saved. Press Refresh to see it on the page."

// facilitatorRefused is error_fragment's "<action>: <reason>".
func facilitatorRefused(reason string) *Refusal {
	return &Refusal{Message: "Facilitator not changed: " + reason}
}

// FacilitatorFacts are what the drawer shows.
type FacilitatorFacts struct {
	// Subtitle is the work, its place and its day.
	Subtitle string
	// Current is "Staff" or the facilitating partner's name; Noun is
	// "meeting" or "training".
	Current, Noun string
	// Selected is the facilitating partner's id ("" for Staff).
	Selected string
	// Partners are every active partner organisation, by name.
	Partners []FacilitatorPartner
}

// FacilitatorPartner is one choice.
type FacilitatorPartner struct{ ID, Name string }

// facilitated is the activity as the drawer and the save read it.
type facilitated struct {
	id, kind, status, delivery, facilitator, name string
	responsible, batchID, partnerName             string
	planned, scheduled                            *time.Time
	schoolName, clusterName                       string
	hasSchool, hasCluster                         bool
}

func readFacilitated(ctx context.Context, q Querier, id string) (*facilitated, error) {
	a := &facilitated{}
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.status, ''), COALESCE(a.delivery_type, ''),
  COALESCE(a.facilitating_partner_id, ''), COALESCE(a.activity_name_snapshot, ''),
  COALESCE(a.responsible_staff_id, ''), COALESCE(a.daily_visit_batch_id, ''), COALESCE(p.name, ''),
  a.planned_date, a.scheduled_date, COALESCE(s.name, ''), COALESCE(c.name, ''), s.id IS NOT NULL, c.id IS NOT NULL
FROM activity a
LEFT JOIN partner p ON p.id = a.facilitating_partner_id
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.kind, &a.status, &a.delivery, &a.facilitator, &a.name, &a.responsible, &a.batchID,
		&a.partnerName, &a.planned, &a.scheduled, &a.schoolName, &a.clusterName, &a.hasSchool, &a.hasCluster)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the activity's facilitator: %w", err)
	}
	return a, nil
}

// current is facilitation.facilitator_label.
func (a *facilitated) current() string {
	switch {
	case a.facilitator == "":
		return "Staff"
	case a.partnerName != "":
		return a.partnerName
	}
	return "Partner"
}

// subtitle is the drawer's: the work's name, its cluster or school, and its
// scheduled day.
func (a *facilitated) subtitle(loc *time.Location) string {
	out := a.name
	if out == "" {
		out = myplan.TypeLabel(a.kind)
	}
	switch {
	case a.hasCluster:
		out += " · " + a.clusterName
	case a.hasSchool:
		out += " · " + a.schoolName
	}
	if a.scheduled != nil {
		day := a.scheduled.In(loc)
		out += fmt.Sprintf(" · %d %s %d", day.Day(), day.Format("Jan"), day.Year())
	}
	return out
}

// FacilitatorDrawer reads the drawer for p, or ErrHandOn: a reader Go does
// not decide for, an activity that is not there, or one the reader may not
// open (the existing view answers those itself).
func (s *Service) FacilitatorDrawer(ctx context.Context, p auth.Principal, id string) (FacilitatorFacts, error) {
	access, err := myplan.ReadActivityAccess(ctx, s.db, p, id, s.now())
	if err != nil {
		return FacilitatorFacts{}, err
	}
	if !access.Decided || !access.Found || !access.Visible {
		return FacilitatorFacts{}, handOn("a facilitator drawer Go does not open")
	}
	a, err := readFacilitated(ctx, s.db, id)
	if err != nil {
		return FacilitatorFacts{}, err
	}
	if a == nil {
		return FacilitatorFacts{}, handOn("no such activity")
	}
	partners, err := activePartners(ctx, s.db)
	if err != nil {
		return FacilitatorFacts{}, err
	}
	return FacilitatorFacts{
		Subtitle: a.subtitle(s.kampala), Current: a.current(), Noun: myplan.SessionNoun(a.kind),
		Selected: a.facilitator, Partners: partners,
	}, nil
}

// activePartners is facilitation.facilitator_partners.
func activePartners(ctx context.Context, q Querier) ([]FacilitatorPartner, error) {
	rows, err := q.Query(ctx, `SELECT id, name FROM partner WHERE deleted_at IS NULL AND active_status ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the partners: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (FacilitatorPartner, error) {
		var p FacilitatorPartner
		err := r.Scan(&p.ID, &p.Name)
		return p, err
	})
}

// SetFacilitator is set_facilitator for p: the saved answer, a *Refusal in
// the existing words, or ErrHandOn.
func (s *Service) SetFacilitator(ctx context.Context, p auth.Principal, id, partnerID string, origin Origin) (string, error) {
	access, err := myplan.ReadActivityAccess(ctx, s.db, p, id, s.now())
	if err != nil {
		return "", err
	}
	if !access.Decided || !access.Found || !access.Visible || !access.Runnable {
		// The view's 403, or _get_for_execution's refusals: not Go's words.
		return "", handOn("a facilitator change Go does not decide")
	}
	a, err := readFacilitated(ctx, s.db, id)
	if err != nil {
		return "", err
	}
	if a == nil {
		return "", handOn("no such activity")
	}
	noun := myplan.SessionNoun(a.kind)
	switch {
	case a.status == "awaiting_owner_approval":
		return "", facilitatorRefused("This visit is still waiting for the school owner's approval. " +
			"Withdraw it and request again for a different date, or wait for their decision.")
	case !myplan.TakesFacilitator(a.kind):
		return "", facilitatorRefused("Only a training or a cluster meeting takes a Facilitated by partner.")
	case a.delivery == "partner":
		return "", facilitatorRefused(fmt.Sprintf("A partner delivers this %s itself, so it has no separate facilitator.", noun))
	case !myplan.FacilitatorEditable(a.status):
		return "", facilitatorRefused(fmt.Sprintf("This %s has happened or been withdrawn; its facilitator can no longer change.", noun))
	}
	partnerID = strings.TrimSpace(partnerID)
	partnerUser := ""
	if partnerID != "" {
		var user *string
		err := s.db.QueryRow(ctx, `SELECT user_id FROM partner WHERE id = $1 AND deleted_at IS NULL AND active_status`, partnerID).Scan(&user)
		if errors.Is(err, pgx.ErrNoRows) {
			return "", facilitatorRefused("Select an active Partner organisation to facilitate.")
		}
		if err != nil {
			return "", fmt.Errorf("activities: reading the partner: %w", err)
		}
		if user != nil {
			partnerUser = *user
		}
	}
	if partnerID == a.facilitator {
		return FacilitatorSaved, nil
	}
	day, err := s.facilitatorDay(ctx, a)
	if err != nil {
		return "", err
	}
	rowID, changed, err := s.writeFacilitator(ctx, p, a, partnerID, day, origin)
	if err != nil || !changed {
		return FacilitatorSaved, err
	}
	s.afterFacilitator(ctx, p, a, partnerID, partnerUser, rowID, origin)
	return FacilitatorSaved, nil
}

// facilitatorDay is the day a change re-prices (_apply_schedule_cost_snapshot
// for dated live work): its batch and owner, or nothing to price. Work
// priced any other way is handed on, and so is a day whose money refuses a
// re-price.
func (s *Service) facilitatorDay(ctx context.Context, a *facilitated) (*[2]string, error) {
	if a.scheduled == nil || a.status == "cancelled" || a.status == "rejected" {
		return nil, nil
	}
	priced, err := pricing.PriceStored(ctx, s.db, a.id)
	if err != nil {
		return nil, handOn("a re-price Go cannot read")
	}
	if priced.Path != pricing.PathDay || a.batchID == "" || a.planned == nil {
		return nil, handOn("a re-price that is not the work's own day")
	}
	var owner string
	var date time.Time
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(responsible_user, ''), visit_date FROM daily_visit_batch WHERE id = $1`, a.batchID).
		Scan(&owner, &date); err != nil {
		return nil, fmt.Errorf("activities: reading the work's day: %w", err)
	}
	if owner == "" || !date.Equal(*a.planned) {
		return nil, handOn("a day that is not the work's planned day")
	}
	if np, ok := s.pricing.(*NativePricing); ok {
		refusal, err := np.dayRefusal(ctx, owner, false, false, date, "", "")
		if err != nil {
			return nil, err
		}
		if refusal != "" {
			return nil, handOn("a day whose money refuses a re-price")
		}
	} else {
		return nil, handOn("no day money check")
	}
	return &[2]string{a.batchID, owner}, nil
}

// writeFacilitator is the transaction: the facilitator under the
// activity's lock, the day's costs to follow and the audit row.
func (s *Service) writeFacilitator(ctx context.Context, p auth.Principal, a *facilitated, partnerID string, day *[2]string, origin Origin) (int64, bool, error) {
	now := s.now()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, false, fmt.Errorf("activities: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, `SELECT gateway_activity_facilitator.set($1, $2, $3)`, a.id, partnerID, now).Scan(&answer); err != nil {
		return 0, false, fmt.Errorf("activities: saving the facilitator: %w", err)
	}
	previous, changed := strings.CutPrefix(answer, "changed:")
	if !changed {
		return 0, false, tx.Commit(ctx)
	}
	var rowID int64
	if day != nil {
		if rowID, err = keepFacilitatorDayCosts(ctx, tx, p, day[0], day[1], origin, now); err != nil {
			return 0, false, err
		}
	}
	cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
	if err != nil {
		return 0, false, err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "activity.facilitator_changed", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(a.id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Payload:   audit.WithStamps(map[string]any{"from": previous, "to": partnerID}, cover),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
	}, now); err != nil {
		return 0, false, fmt.Errorf("activities: writing the audit row: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, false, fmt.Errorf("activities: committing the facilitator: %w", err)
	}
	return rowID, true, nil
}

// keepFacilitatorDayCosts is the costs to follow for one day the change re-prices.
func keepFacilitatorDayCosts(ctx context.Context, tx pgx.Tx, p auth.Principal, batchID, owner string, origin Origin, now time.Time) (int64, error) {
	steps, err := json.Marshal(map[string]any{
		"days": [][]string{{batchID, owner}}, "together": false,
		"weeks": []any{}, "months": []any{}, "notes": []any{}, "change": nil,
	})
	if err != nil {
		return 0, err
	}
	owners, _ := json.Marshal([]string{owner})
	provenance, _ := json.Marshal(map[string]any{
		"ip": nilIfEmpty(origin.IP), "agent": nilIfEmpty(origin.UserAgent),
		"correlation": nilIfEmpty(origin.CorrelationID), "acting": nil,
	})
	var id int64
	err = tx.QueryRow(ctx, `
INSERT INTO daily_visit_costs_to_follow (created_at, updated_at, owners, asked_by, asked_by_role, steps,
  provenance, attempts, held_reason)
VALUES ($1, $1, $2, $3, $4, $5, $6, 0, '') RETURNING id`,
		now, owners, p.UserID, p.ActiveRole, steps, provenance).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("activities: keeping the costs to follow: %w", err)
	}
	return id, nil
}

// afterFacilitator is what follows the commit: the ledger's mark (the
// activity's save marks its owner's year), the day's price, and the
// partner told (_tell_facilitating_partner). None of it undoes the change.
func (s *Service) afterFacilitator(ctx context.Context, p auth.Principal, a *facilitated, partnerID, partnerUser string, rowID int64, origin Origin) {
	if in(rules.LedgerCreditedTypes, a.kind) && a.planned != nil {
		if err := s.markOwnerYears(ctx, a.responsible, *a.planned); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", a.id, "err", err)
		}
	}
	if rowID != 0 {
		if err := s.pricing.Settle(ctx, []int64{rowID}, a.id); err != nil {
			s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
				"activity", a.id, "row", rowID, "err", err)
		}
	}
	if partnerID == "" || partnerUser == "" {
		return
	}
	what := "training"
	switch {
	case myplan.SessionNoun(a.kind) == "meeting":
		what = "cluster meeting"
	case a.hasCluster:
		what = "group training"
	}
	where := "a cluster"
	switch {
	case a.hasCluster && a.clusterName != "":
		where = a.clusterName
	case !a.hasCluster && a.hasSchool && a.schoolName != "":
		where = a.schoolName
	}
	when := ""
	if day := a.planned; day != nil {
		when = " on " + day.Format("02 Jan 2006")
	} else if a.scheduled != nil {
		when = " on " + a.scheduled.In(s.kampala).Format("02 Jan 2006")
	}
	if err := SendNotices(ctx, s.db, s.noticePush, s.live, s.logger, s.now(), partnerID, p.UserID, origin, Notice{
		Title: "You are facilitating a " + what,
		Body:  fmt.Sprintf("Edify booked your organisation to facilitate the %s at %s%s. Its facilitation fee is invoiced through Partner Invoices.", what, where, when),
		Event: "partner_facilitation_booked", Category: "partner", ContextType: "Partner", Priority: "normal",
	}, []NoticeTo{{UserID: partnerUser}}); err != nil {
		s.logger.Warn("activities: the facilitating partner was not told", "activity", a.id, "err", err)
	}
}
