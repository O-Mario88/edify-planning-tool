package activities

// The eighth save (docs/migration/48): a Group Training delivered online,
// from the same cluster drawer opened with action=online (owner,
// 2026-10-09: "online training fetches no cost it is free"). It is the
// Group Training of docs/migration/38 with three differences, each where
// the existing application makes it:
//
//   - the view posts delivery_mode=online and puts programmeDeliveryMode
//     "online" in the payload (schedule_action_view 2357–2363), stored as
//     activity.programme_delivery_mode (_create 3395–3399);
//   - `_create` asks no cost preview of it (3129–3135: asked_for_online);
//   - `_price_activity`'s online branch (services 1174–1190) joins no day and
//     writes the cost revision at UGX 0 inside the save: the period columns
//     and the price on the row, one current activity_cost_snapshot and its
//     `activity.cost.calculated` audit entry, before `activity.scheduled`.
//     Nothing else: no cost line, no advance, no week or month to refile, no
//     costs to follow.
//
// The revision's figures are the existing application's (calculate_dual,
// read only through the day check, gateway_relay._online_cost); Go writes
// them. Everything 38 hands on is handed on here too.

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	// apps.activities.online_training.ONLINE.
	onlineDelivery = "online"
	// ActivityCostSnapshot.cost_status's default.
	estimatedCost = "estimated"
)

// OnlineCost is the cost revision the existing save writes for an online
// Group Training (gateway_relay._online_cost), as the day check answers it.
type OnlineCost struct {
	OperationalCardID      *string         `json:"operationalCardId"`
	OperationalCardVersion *int            `json:"operationalCardVersion"`
	ReferenceCardID        *string         `json:"referenceCardId"`
	ReferenceCardVersion   *int            `json:"referenceCardVersion"`
	ReferenceCost          *int64          `json:"referenceCost"`
	ReferenceBreakdown     json.RawMessage `json:"referenceBreakdown"`
	OperationalCost        int64           `json:"operationalCost"`
	OperationalBreakdown   json.RawMessage `json:"operationalBreakdown"`
	CalculationInputs      json.RawMessage `json:"calculationInputs"`
	Warnings               json.RawMessage `json:"warnings"`
	MissingConfiguration   json.RawMessage `json:"missingConfiguration"`
	CostMissing            bool            `json:"costMissing"`
	CalculatedBy           *string         `json:"calculatedBy"`
}

// takeable is whether Go writes this revision: a free one, priced against a
// card, nothing missing, every figure given.
func (c *OnlineCost) takeable() bool {
	if c == nil || c.CostMissing || c.OperationalCost != 0 || c.OperationalCardID == nil ||
		c.OperationalCardVersion == nil {
		return false
	}
	for _, raw := range []json.RawMessage{c.ReferenceBreakdown, c.OperationalBreakdown, c.CalculationInputs,
		c.Warnings, c.MissingConfiguration} {
		if len(raw) == 0 || string(raw) == "null" {
			return false
		}
	}
	return true
}

// onlinePeriods are apply_to_activities' period columns for the planned
// day (costing_service 1560–1574): the week (Monday to Sunday), the month,
// and the quarter and FY of the day itself; `fy` follows the day.
type onlinePeriods struct {
	weekStart, weekEnd time.Time
	month              int
	quarter, fy        string
}

func periodsOf(planned time.Time) onlinePeriods {
	day := time.Date(planned.Year(), planned.Month(), planned.Day(), 0, 0, 0, 0, time.UTC)
	start := day.AddDate(0, 0, -((int(day.Weekday()) + 6) % 7))
	return onlinePeriods{
		weekStart: start, weekEnd: start.AddDate(0, 0, 6), month: int(day.Month()),
		quarter: quarterOf(day), fy: schooldirectory.OperationalFY(day),
	}
}

// onlineFields are the columns only an online session's insert sets: its
// periods, as the revision leaves them.
func (r activityRow) onlineFields() []struct {
	name  string
	value any
} {
	if r.group == nil || !r.group.online {
		return nil
	}
	p := periodsOf(r.plannedDate)
	return []struct {
		name  string
		value any
	}{
		{"week_start_date", p.weekStart.Format(time.DateOnly)}, {"week_end_date", p.weekEnd.Format(time.DateOnly)},
		{"month", p.month}, {"fiscal_year", p.fy},
	}
}

// takeOnline is the day check's answer for an online session: the revision
// Go will write, or a hand-on.
func takeOnline(row *activityRow, verdict DayVerdict) error {
	if verdict.Refusal != "" || verdict.Pooled || !verdict.Online.takeable() {
		return handOn("an online training whose cost revision Go does not write")
	}
	// The revision moves the row's quarter and FY onto the planned day.
	p := periodsOf(row.plannedDate)
	row.quarter, row.fy = p.quarter, p.fy
	return nil
}

// writeOnlineCost is the revision inside the save's transaction: one
// current snapshot (the first for a new activity) and its audit entry,
// with the actor's cover, as apply_to_activities writes them.
func (s *Service) writeOnlineCost(ctx context.Context, tx pgx.Tx, pl *plan) error {
	c := pl.verdict.Online
	r := pl.row
	id := cuid.New()
	now := s.now()
	calculatedBy := ""
	if c.CalculatedBy != nil {
		calculatedBy = *c.CalculatedBy
	}
	if _, err := tx.Exec(ctx, `INSERT INTO activity_cost_snapshot (created_at, updated_at, id, sequence, is_current,
  activity_catalogue_item_id, activity_catalogue_version, costing_profile_version, reference_cost, operational_cost,
  approved_operating_limit, amount_disbursed, actual_accounted_spend, unused_balance, reimbursement_amount,
  calculation_inputs, reference_breakdown, operational_breakdown, warnings, missing_configuration, calculated_at,
  calculated_by, recalculation_reason, approved_by, approved_at, cost_status, activity_id, operational_rate_card_id,
  reference_rate_card_id, supersedes_id)
VALUES ($1, $1, $2, 1, true, $3, $4, $5, $6, $7, NULL, 0, 0, 0, 0, $8, $9, $10, $11, $12, $1, $13, NULL, NULL, NULL,
  $14, $15, $16, $17, NULL)`,
		now, id, r.item.ID, r.version, optString(r.item.CostingProfile), c.ReferenceCost, c.OperationalCost,
		string(c.CalculationInputs), string(c.ReferenceBreakdown), string(c.OperationalBreakdown),
		string(c.Warnings), string(c.MissingConfiguration), optString(calculatedBy), estimatedCost, r.id,
		c.OperationalCardID, c.ReferenceCardID); err != nil {
		return fmt.Errorf("activities: writing the cost revision: %w", err)
	}
	cover, err := coverageStamp(ctx, tx, calculatedBy, now)
	if err != nil {
		return err
	}
	payload := map[string]any{
		"activityId": r.id, "sequence": 1, "operationalCost": c.OperationalCost,
		"operationalRateCardVersion": *c.OperationalCardVersion,
		"referenceConfigured":        c.ReferenceCost != nil, "referenceRateCardVersion": nil,
	}
	if c.ReferenceCardVersion != nil {
		payload["referenceRateCardVersion"] = *c.ReferenceCardVersion
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "activity.cost.calculated", SubjectKind: audit.Text("ActivityCostSnapshot"), SubjectID: audit.Text(id),
		ActorID: audit.Text(calculatedBy), Success: true, Payload: withStamps(payload, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, now); err != nil {
		return fmt.Errorf("activities: auditing the cost revision: %w", err)
	}
	return nil
}

// afterOnlineCommit is afterCommit for an online session: the ledger's
// mark and `activity.scheduled`, then the realtime announcement the row's
// post_save makes; nothing is left to settle.
func (s *Service) afterOnlineCommit(ctx context.Context, pl *plan) {
	if err := s.markLedger(ctx, pl); err != nil {
		s.logger.Warn("activities: the target ledger was not marked", "activity", pl.row.id, "err", err)
	}
	if err := s.auditScheduled(ctx, pl); err != nil {
		s.logger.Warn("activities: the scheduled audit row was not written", "activity", pl.row.id, "err", err)
	}
	if teller, ok := s.pricing.(Announcer); ok {
		if err := teller.Announce(ctx, pl.row.id); err != nil {
			s.logger.Warn("activities: the online training was not announced", "activity", pl.row.id, "err", err)
		}
	}
}
