package partnerassigned

// Who on a Partner's team delivers one of its activities
// (partner_views.partner_delivery_member_view, apps.partners.delivery_team):
// the drawer that names them, chosen from the team, and its save.

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrDeliveryNotFound is the view's 404: no such work of the reader's
// organisation.
var ErrDeliveryNotFound = errors.New("partnerassigned: no such work of the organisation's")

// ErrDeliveryHandOn is a save Go does not make: naming the team member on
// a loan-use verification visit, whose save also links it to its loan.
var ErrDeliveryHandOn = errors.New("partnerassigned: this save is Django's")

// loanVerificationCode is LOAN_VERIFICATION_CODE.
const loanVerificationCode = "BT_UG_LOAN_USE_VERIFICATION"

// DeliveryError is the save refused in its words.
type DeliveryError struct{ Message string }

func (e *DeliveryError) Error() string { return e.Message }

const (
	leadsTeamRefusal = "Your organisation's Partner Admin chooses who delivers each piece of work."
	finishedRefusal  = "This work is finished or was called off; who delivered it is part of its record now."
	teamHelp         = "Your team is the Staff and volunteers list on your organisation's profile. Add someone there to choose them here."
)

// deliveryWork is the activity and the organisation that delivers it.
type deliveryWork struct {
	id, status, activityType, snapshot, contact string
	place                                       string
	day                                         *time.Time
	partnerID, partnerUser                      string
}

// readDeliveryWork is the view's lookup: the activity the reader's
// organisation delivers or facilitates, and which of them it is.
func readDeliveryWork(ctx context.Context, db schooldirectory.Querier, p auth.Principal, activityID string) (*deliveryWork, error) {
	ids, err := PartnerIDs(ctx, db, p)
	if err != nil || len(ids) == 0 {
		return nil, errOr(err, ErrDeliveryNotFound)
	}
	w := &deliveryWork{}
	var assigned, facilitating string
	var scheduled *time.Time
	var planned *time.Time
	err = db.QueryRow(ctx, `SELECT a.id, COALESCE(a.status, ''), COALESCE(a.activity_type, ''), COALESCE(a.activity_name_snapshot, ''),
  COALESCE(a.delivery_contact_name, ''), COALESCE(s.name, c.name, ''), a.scheduled_date, a.planned_date,
  COALESCE(a.assigned_partner_id, ''), COALESCE(a.facilitating_partner_id, '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.id = $1 AND a.deleted_at IS NULL AND (a.assigned_partner_id = ANY($2) OR a.facilitating_partner_id = ANY($2))`, activityID, ids).
		Scan(&w.id, &w.status, &w.activityType, &w.snapshot, &w.contact, &w.place, &scheduled, &planned, &assigned, &facilitating)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrDeliveryNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: the work: %w", err)
	}
	switch {
	case slices.Contains(ids, assigned):
		w.partnerID = assigned
	case slices.Contains(ids, facilitating):
		w.partnerID = facilitating
	}
	if err := db.QueryRow(ctx, `SELECT COALESCE(user_id, '') FROM partner WHERE id = $1`, w.partnerID).Scan(&w.partnerUser); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrDeliveryNotFound
		}
		return nil, fmt.Errorf("partnerassigned: the organisation: %w", err)
	}
	if scheduled != nil {
		day := scheduled.In(zone)
		d := time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)
		w.day = &d
	} else {
		w.day = planned
	}
	return w, nil
}

// leadsTeam is member_logins.leads_team: the Admin, the organisation's own
// login, or its Partner Admin.
func leadsTeam(ctx context.Context, db schooldirectory.Querier, p auth.Principal, w *deliveryWork) (bool, error) {
	if p.ActiveRole == roleAdmin || (w.partnerUser != "" && w.partnerUser == p.UserID) {
		return true, nil
	}
	if p.ActiveRole != rolePartnerAdmin {
		return false, nil
	}
	ids, err := PartnerIDs(ctx, db, p)
	return slices.Contains(ids, w.partnerID), err
}

// mayRename is delivery_team.may_rename.
func mayRename(status string) bool {
	return !slices.Contains(rules.CompletedWorkStatuses, status) && !slices.Contains(rules.CalledOffStatuses, status)
}

// teamNames is delivery_team.team_names: the active roster in its order,
// then the login's own name when it is not on it.
func teamNames(ctx context.Context, db schooldirectory.Querier, p auth.Principal, partnerID string) ([]string, error) {
	rows, err := db.Query(ctx, `SELECT name FROM partner_member WHERE partner_id = $1 AND active ORDER BY role, name`, partnerID)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: the team: %w", err)
	}
	all, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: the team: %w", err)
	}
	names, seen := []string{}, map[string]bool{}
	for _, n := range all {
		if n = strings.TrimSpace(n); n != "" {
			names = append(names, n)
			seen[strings.ToLower(n)] = true
		}
	}
	if own := strings.TrimSpace(p.Name); own != "" && !seen[strings.ToLower(own)] {
		names = append(names, own)
	}
	return names, nil
}

func notAvailable(message string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{Title: "Not available", HasRequired: true, CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: message, Tone: "warning"}}}}}
}

// DeliveryDrawer is the view's GET: the drawer, or its refusal drawn as
// the drawer, as the feed reads them.
func DeliveryDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, activityID string) (*screensv1.PageDrawer, error) {
	w, err := readDeliveryWork(ctx, db, p, activityID)
	if err != nil {
		return nil, err
	}
	leads, err := leadsTeam(ctx, db, p, w)
	if err != nil {
		return nil, err
	}
	if !leads {
		return notAvailable(leadsTeamRefusal), nil
	}
	if !mayRename(w.status) {
		return notAvailable(finishedRefusal), nil
	}
	team, err := teamNames(ctx, db, p, w.partnerID)
	if err != nil {
		return nil, err
	}
	noun := "work"
	if slices.Contains(rules.TrainingTypes, w.activityType) {
		noun = "training"
	}
	subtitle := w.snapshot
	if subtitle == "" {
		subtitle = labelOr(rules.ActivityTypes[w.activityType], w.activityType)
	}
	if w.place != "" {
		subtitle += " · " + w.place
	}
	if w.day != nil {
		subtitle += " · " + w.day.Format("2 Jan 2006")
	}
	options, value := []*screensv1.DrawerOption{}, ""
	for _, n := range team {
		options = append(options, &screensv1.DrawerOption{Value: n, Label: n})
		if n == w.contact {
			value = n
		}
	}
	if value == "" && len(team) > 0 {
		value = team[0]
	}
	now := w.contact
	if now == "" {
		now = "Nobody named yet"
	}
	return &screensv1.PageDrawer{Title: "Who delivers this " + noun, Subtitle: subtitle, HasRequired: true, SubmitLabel: "Save",
		CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Text{Text: "Now: " + now}},
			{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "delivery_contact_name", Label: "Team member",
				Kind: "select", Value: value, Required: true, Help: teamHelp, Options: options}}},
		}}, nil
}

// NameMember is delivery_team.name_member: the team member named on the
// work, audited when it changes. It answers who delivers it.
func NameMember(ctx context.Context, pool *pgxpool.Pool, p auth.Principal, activityID, name string, origin activities.Origin,
	now time.Time) (string, error) {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("partnerassigned: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	ids, err := PartnerIDs(ctx, tx, p)
	if err != nil {
		return "", err
	}
	if len(ids) == 0 {
		return "", &DeliveryError{"Only a partner account names its own team's work."}
	}
	var status, previous, assigned, facilitating, school, catalogue string
	var iaConfirmedAt *time.Time
	err = tx.QueryRow(ctx, `SELECT COALESCE(status, ''), COALESCE(delivery_contact_name, ''), COALESCE(assigned_partner_id, ''),
  COALESCE(facilitating_partner_id, ''), COALESCE(school_id, ''), COALESCE(catalogue_item_id, ''), ia_confirmed_at
FROM activity WHERE id = $1 AND deleted_at IS NULL FOR UPDATE`, activityID).
		Scan(&status, &previous, &assigned, &facilitating, &school, &catalogue, &iaConfirmedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", &DeliveryError{"Activity not found."}
	}
	if err != nil {
		return "", fmt.Errorf("partnerassigned: the work: %w", err)
	}
	w := &deliveryWork{id: activityID, status: status}
	switch {
	case slices.Contains(ids, assigned):
		w.partnerID = assigned
	case slices.Contains(ids, facilitating):
		w.partnerID = facilitating
	default:
		return "", &DeliveryError{"This activity belongs to another organisation."}
	}
	if !mayRename(status) {
		return "", &DeliveryError{finishedRefusal}
	}
	if err := tx.QueryRow(ctx, `SELECT COALESCE(user_id, '') FROM partner WHERE id = $1`, w.partnerID).Scan(&w.partnerUser); err != nil {
		return "", fmt.Errorf("partnerassigned: the organisation: %w", err)
	}
	leads, err := leadsTeam(ctx, tx, p, w)
	if err != nil {
		return "", err
	}
	if !leads {
		return "", &DeliveryError{"Only the organisation's Partner Admin or an Edify Admin manages its team."}
	}
	team, err := teamNames(ctx, tx, p, w.partnerID)
	if err != nil {
		return "", err
	}
	wanted := strings.TrimSpace(name)
	if len([]rune(wanted)) < 2 {
		return "", &DeliveryError{"Choose the team member who will deliver this work."}
	}
	chosen := ""
	for _, member := range team {
		if strings.EqualFold(member, wanted) {
			chosen = member
			break
		}
	}
	if chosen == "" {
		return "", &DeliveryError{wanted + " is not on your organisation's team. Add them under Staff and volunteers on your " +
			"organisation's profile, then choose them here."}
	}
	if chosen != previous {
		if school != "" && catalogue != "" {
			// The save bridge also links a loan-use verification visit to
			// its loan (_link_planned_loan_verification_activity).
			var loanVisit bool
			if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity_catalogue_item WHERE id = $1 AND stable_code = $2)`,
				catalogue, loanVerificationCode).Scan(&loanVisit); err != nil {
				return "", fmt.Errorf("partnerassigned: the work's catalogue item: %w", err)
			}
			if loanVisit {
				return "", ErrDeliveryHandOn
			}
		}
		if _, err := tx.Exec(ctx, `UPDATE activity SET delivery_contact_name = $2, updated_at = $3 WHERE id = $1`, activityID, chosen, now); err != nil {
			return "", fmt.Errorf("partnerassigned: naming the team member: %w", err)
		}
		if err := plreview.RaiseActivitySaved(ctx, tx, activityID, status, iaConfirmedAt, now); err != nil {
			return "", err
		}
		cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
		if err != nil {
			return "", err
		}
		if _, err := audit.Append(ctx, tx, audit.Entry{Action: "partner.delivery_member_named", SubjectKind: audit.Text("activity"),
			SubjectID: audit.Text(activityID), ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
			IPAddress: audit.Text(origin.IP), UserAgent: audit.Text(origin.UserAgent), CorrelationID: audit.Text(origin.CorrelationID),
			Payload: audit.WithStamps(map[string]any{"partnerId": w.partnerID, "previous": previous, "new": chosen}, cover)}, now); err != nil {
			return "", fmt.Errorf("partnerassigned: auditing the team member: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("partnerassigned: committing the team member: %w", err)
	}
	return chosen + " will deliver this work.", nil
}

func labelOr(label, otherwise string) string {
	if label == "" {
		return otherwise
	}
	return label
}

func errOr(err, otherwise error) error {
	if err != nil {
		return err
	}
	return otherwise
}
