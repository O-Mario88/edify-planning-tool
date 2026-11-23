package plreview

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	ssaYearHeldCode = "ED001" // confirm_visit_ssa: another record holds the school's year
	ssaBasisVisit   = "pl_approval"
)

// ledgerMark is one owner's year for the targets ledger to rebuild.
type ledgerMark struct{ owner, fy string }

// confirmedSSAEvents is what saving a confirmed SsaRecord raises, with the
// baseline capture confirm_record queues after it.
func confirmedSSAEvents(recordID, schoolPK string, verifiedAt time.Time) []outboxEvent {
	version := pythonISO(verifiedAt)
	record := map[string]string{"ssaRecordId": recordID}
	school := map[string]string{"schoolId": schoolPK}
	return []outboxEvent{
		{Type: "bt.ssa.confirmed", Key: "bt.ssa.confirmed:" + recordID + ":" + version, Payload: record},
		{Type: "ssa.recommendations.generate", Key: "ssa.recommendations:" + recordID + ":" + version, Payload: record},
		{Type: "projects.impact.refresh", Key: "projects.impact:" + schoolPK + ":ssa:" + version, Payload: school},
		{Type: "projects.baselines.capture", Key: "projects.baselines.capture:" + schoolPK + ":ssa:" + recordID + ":confirmed", Payload: school},
	}
}

// confirmedSSA is one record the approval confirmed.
type confirmedSSA struct {
	id, school, name string
	collectedBy      *string
	day              time.Time
}

// confirmVisitSSA is pl_confirmation.confirm_visit_ssa inside the approval:
// partner SSA stays with Impact Assessment, whoever approves the visit. A year
// another record holds refuses the whole approval in the existing words.
func confirmVisitSSA(ctx context.Context, tx pgx.Tx, r Review, reviewerID string, now time.Time) ([]ledgerMark, error) {
	if r.DeliveryType == partnerDelivery {
		return nil, nil
	}
	rows, err := tx.Query(ctx, `SELECT record_id, school_pk, school_name, collected_by, ssa_day
  FROM gateway_pl_review.confirm_visit_ssa($1, $2, $3, $4)`, r.ID, reviewerID, now, schooldirectory.OperationalFY(now))
	if err != nil {
		return nil, fmt.Errorf("plreview: confirming the visit's SSA: %w", err)
	}
	records, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (confirmedSSA, error) {
		var c confirmedSSA
		err := row.Scan(&c.id, &c.school, &c.name, &c.collectedBy, &c.day)
		return c, err
	})
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == ssaYearHeldCode {
		return nil, &ReviewRefusal{Message: "SSA already exists for this school for FY" + pgErr.Message + ". The record was not added."}
	}
	if err != nil {
		return nil, fmt.Errorf("plreview: confirming the visit's SSA: %w", err)
	}
	marks := []ledgerMark{}
	for _, record := range records {
		if err := raiseEvents(ctx, tx, confirmedSSAEvents(record.id, record.school, now), now); err != nil {
			return nil, err
		}
		var collectedBy any
		if record.collectedBy != nil {
			collectedBy = *record.collectedBy
			day := record.day.UTC()
			marks = append(marks, ledgerMark{
				owner: *record.collectedBy,
				fy:    schooldirectory.OperationalFY(time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)),
			})
		}
		entry := stamped(ctx, audit.Entry{
			Action: "ssa_verify", SubjectKind: audit.Text("SsaRecord"), SubjectID: audit.Text(record.id),
			ActorID: audit.Text(reviewerID), ActorRole: audit.Text(rules.LeadRole),
			Payload: map[string]any{
				"schoolId": record.school, "schoolName": record.name, "basis": ssaBasisVisit,
				"collectedBy": collectedBy, "sourceActivityId": r.ID,
			},
		})
		if err := appendAudit(ctx, tx, entry, now); err != nil {
			return nil, fmt.Errorf("plreview: auditing the SSA's confirmation: %w", err)
		}
	}
	return marks, nil
}

// settleRecommendations is plan_alignment.settle_recommendations for verified
// work, with the audit rows it writes as the system.
func settleRecommendations(ctx context.Context, tx pgx.Tx, r Review, now time.Time) error {
	var delivered, released []string
	if err := tx.QueryRow(ctx, `SELECT delivered, released FROM gateway_pl_review.settle_recommendations($1, $2)`,
		r.ID, now).Scan(&delivered, &released); err != nil {
		return fmt.Errorf("plreview: settling the recommendations: %w", err)
	}
	for _, outcome := range []struct {
		action string
		ids    []string
	}{{"ssa.recommendation_delivered", delivered}, {"ssa.recommendation_released", released}} {
		if len(outcome.ids) == 0 {
			continue
		}
		ids := make([]any, 0, min(len(outcome.ids), maxAuditedRecommendations))
		for _, id := range outcome.ids[:min(len(outcome.ids), maxAuditedRecommendations)] {
			ids = append(ids, id)
		}
		noRole := ""
		entry := stamped(ctx, audit.Entry{
			Action: outcome.action, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(r.ID),
			ActorID: audit.Text("system"), ActorRole: &noRole,
			Payload: map[string]any{"recommendationIds": ids, "intervention": r.Intervention, "status": statusVerified},
		})
		if err := appendAudit(ctx, tx, entry, now); err != nil {
			return fmt.Errorf("plreview: auditing the recommendations: %w", err)
		}
	}
	return nil
}

// maxAuditedRecommendations is how many ids one audit row names.
const maxAuditedRecommendations = 200

// linkLoanVisit is the Business Transformation bridge every save of the
// activity runs: a loan-use visit answers the school's oldest waiting need.
func linkLoanVisit(ctx context.Context, tx pgx.Tx, activityID string, now time.Time) error {
	if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.link_loan_visit($1, $2, $3)`, cuid.New(), activityID, now); err != nil {
		return fmt.Errorf("plreview: linking the loan-use visit: %w", err)
	}
	return nil
}
