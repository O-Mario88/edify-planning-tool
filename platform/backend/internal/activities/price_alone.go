package activities

// Pricing one activity on its own, with the existing application absent:
// _apply_schedule_cost_snapshot for work on no day of its own (a Work Plan
// programme activity): its cost as the single cost writer prices it
// (pricing.PriceStored, the "alone" path), written through the same function
// the day settlement writes with, its advance opened, and its owner's week
// and month re-filed. Inside the caller's transaction.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// AlonePricer prices one activity on its own in a transaction it is given.
type AlonePricer interface {
	PriceAloneInTx(ctx context.Context, tx pgx.Tx, activityID, actorID, actorRole string, inputs map[string]any) error
}

// errCostMissing is an activity the catalogue cannot price yet: the existing
// create refuses it in words Go does not draw.
var errCostMissing = errors.New("activities: the activity's cost is missing a rate")

// errReferenceCard is a published regional reference card, which the create
// also prices against for its warnings: not ported, so handed on.
var errReferenceCard = errors.New("activities: a regional reference card is published")

const (
	referenceMissingWarning = "Regional Standard Funding Rate Card has not been configured."
	belowMinimumWarning     = "One or more operational rates are below an approved minimum."
)

// PriceAloneInTx is that pricing. inputs is the snapshot's
// calculation_inputs (_costing_input as the create builds it).
func (n *NativePricing) PriceAloneInTx(ctx context.Context, tx pgx.Tx, activityID, actorID, actorRole string, inputs map[string]any) error {
	priced, err := pricing.PriceStored(ctx, tx, activityID)
	if err != nil {
		return err
	}
	if priced.Path != pricing.PathAlone {
		return fmt.Errorf("activities: %s is priced on its %s path, not alone", activityID, priced.Path)
	}
	if priced.Cost.CostMissing || len(priced.Cost.MissingItems) > 0 {
		return errCostMissing
	}
	var responsible string
	var planned time.Time
	if err := tx.QueryRow(ctx, `SELECT responsible_staff_id, planned_date FROM activity WHERE id = $1`, activityID).Scan(&responsible, &planned); err != nil {
		return fmt.Errorf("activities: reading the activity to price: %w", err)
	}
	prof, err := n.loadStaffProfile(ctx, responsible)
	if err != nil {
		return err
	}
	ownerUID := prof.UserID
	if ownerUID == "" {
		ownerUID = responsible
	}
	periods := periodsOf(planned)
	card, err := n.loadRateCard(ctx, periods.fy, "operational")
	if err != nil {
		return err
	}
	if card == nil {
		return fmt.Errorf("activities: no active operational cost catalogue for FY %s", periods.fy)
	}
	var reference bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cost_catalogue WHERE kind = 'reference' AND status = 'published')`).Scan(&reference); err != nil {
		return fmt.Errorf("activities: reading the reference card: %w", err)
	}
	if reference {
		return errReferenceCard
	}
	lines, total := aloneLines(priced.Cost)
	linesJSON, err := json.Marshal(lines)
	if err != nil {
		return err
	}
	inputsJSON, err := json.Marshal(inputs)
	if err != nil {
		return err
	}
	calcBy := actorID
	if calcBy == "" {
		calcBy = ownerUID
	}
	respRole := prof.ActiveRole
	if respRole == "" {
		respRole = actorRole
	}
	now := n.clock()
	snapshotID := cuid.New()
	var seq int
	if err := tx.QueryRow(ctx, `
SELECT gateway_costing.apply_activity_cost(
  $1, $2, $3, $4::date, $5::date, $6, $7, $8, $9, $10, $11, $12, $13, $14,
  $15, $16::jsonb, $17::jsonb, $18::jsonb, $19::jsonb, $20, $21, $22
)`,
		activityID, total, false,
		periods.weekStart.Format(time.DateOnly), periods.weekEnd.Format(time.DateOnly),
		periods.month, periods.fy, periods.quarter,
		card.ID, card.Version, card.Currency,
		ownerUID, respRole, calcBy,
		snapshotID, string(inputsJSON), string(linesJSON), `[]`, string(linesJSON),
		cuid.New(), cuid.New(), now,
	).Scan(&seq); err != nil {
		return fmt.Errorf("activities: applying the activity's cost: %w", err)
	}
	if err := noteAloneSnapshot(ctx, tx, snapshotID, card.ID, lines); err != nil {
		return err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "activity.cost.calculated", SubjectKind: audit.Text("ActivityCostSnapshot"),
		SubjectID: audit.Text(snapshotID), ActorID: audit.Text(calcBy), Success: true,
		Payload: map[string]any{
			"activityId": activityID, "sequence": seq, "operationalCost": total,
			"operationalRateCardVersion": card.Version, "referenceConfigured": false, "referenceRateCardVersion": nil,
		},
	}, now); err != nil {
		return fmt.Errorf("activities: appending the cost audit row: %w", err)
	}
	money := newDayMoney()
	if err := openDayMoney(ctx, tx, []string{activityID}, ownerUID, planned, now, money); err != nil {
		return err
	}
	return refileDayMoney(ctx, tx, money, now)
}

// aloneLine is one line as the snapshot's breakdown and the cost lines keep it.
type aloneLine struct {
	Key          string `json:"key"`
	Label        string `json:"label"`
	Unit         int64  `json:"unit"`
	Qty          int64  `json:"qty"`
	Amount       int64  `json:"amount"`
	Missing      bool   `json:"missing"`
	LineItemType string `json:"lineItemType"`
}

func aloneLines(cost costing.Cost) ([]aloneLine, int64) {
	lines := make([]aloneLine, 0, len(cost.Lines))
	var total int64
	for _, l := range cost.Lines {
		unit := int64(0)
		if l.Unit != nil {
			unit = *l.Unit
		}
		lines = append(lines, aloneLine{Key: l.Key, Label: l.Label, Unit: unit, Qty: l.Qty, Amount: l.Amount,
			Missing: l.Missing, LineItemType: costing.LineItemType(l.Key)})
		total += l.Amount
	}
	return lines, total
}

// fyOf is the operational year of a day.
func fyOf(day time.Time) string { return schooldirectory.OperationalFY(day) }

// pricingInput is pricing.StoredInput, for the snapshot's inputs.
func pricingInput(ctx context.Context, tx pgx.Tx, id string) (pricing.Input, error) {
	return pricing.StoredInput(ctx, tx, id)
}

// noteAloneSnapshot is costing_service.preview's warnings for the lines
// priced, with no recalculation reason, as the create writes them.
func noteAloneSnapshot(ctx context.Context, tx pgx.Tx, snapshotID, cardID string, lines []aloneLine) error {
	keys := make([]string, 0, len(lines))
	for _, l := range lines {
		keys = append(keys, l.Key)
	}
	var below bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cost_setting WHERE catalogue_id = $1 AND key = ANY($2)
  AND approved_minimum IS NOT NULL AND unit_cost < approved_minimum)`, cardID, keys).Scan(&below); err != nil {
		return fmt.Errorf("activities: reading the rates' minimums: %w", err)
	}
	warnings := []string{}
	if below {
		warnings = append(warnings, belowMinimumWarning)
	}
	warnings = append(warnings, referenceMissingWarning)
	raw, err := json.Marshal(warnings)
	if err != nil {
		return err
	}
	var noted bool
	if err := tx.QueryRow(ctx, `SELECT gateway_costing.note_snapshot($1, $2::jsonb, NULL)`, snapshotID, string(raw)).Scan(&noted); err != nil {
		return fmt.Errorf("activities: noting the snapshot: %w", err)
	}
	if !noted {
		return fmt.Errorf("activities: the snapshot %s was not written", snapshotID)
	}
	return nil
}
