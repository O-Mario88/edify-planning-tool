// Package integrationsync is the Salesforce and NetSuite sync handlers the
// outbox runs (apps.integrations.services). The existing transport is not
// built: push_to_external and validate_external_reference refuse, so an
// event only succeeds where a reference pasted by staff already exists, which
// is recorded as reconciled; every other event fails with the existing
// refusal and is retried, then dead-lettered, as the existing outbox does.
// The sync flags are off in every environment, so none of these events is
// raised today. Inside the caller's transaction.
package integrationsync

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	salesforce = "salesforce"
	netsuite   = "netsuite"
	reconciled = "reconciled_manual"
)

// notConfigured is IntegrationNotConfigured from push_to_external, as the
// outbox records it ("<type>: <message>").
func notConfigured(system string) error {
	return fmt.Errorf("IntegrationNotConfigured: %s transport is not configured — set the API credentials and "+
		"implement push_to_external before enabling the sync flag.", system)
}

// referenceNotConfigured is validate_external_reference's refusal.
func referenceNotConfigured(system, resource, externalID string) error {
	return fmt.Errorf("IntegrationNotConfigured: %s reference validation is not configured for %s (%s).",
		system, resource, externalID)
}

// errNoLoanReference is the school loan handler's ValueError.
var errNoLoanReference = errors.New("ValueError: School loan has no confirmed Salesforce reference.")

// SalesforceActivity is `integrations.salesforce.activity`.
func SalesforceActivity(ctx context.Context, tx pgx.Tx, activityID string, now time.Time) error {
	var reference *string
	err := tx.QueryRow(ctx, `SELECT salesforce_activity_id FROM activity WHERE id = $1 AND deleted_at IS NULL`, activityID).
		Scan(&reference)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("integrationsync: reading the activity: %w", err)
	}
	if reference != nil && *reference != "" {
		return record(ctx, tx, salesforce, "activity", activityID, *reference, now)
	}
	return notConfigured(salesforce)
}

// SalesforceSchoolLoan is `integrations.salesforce.school_loan`.
func SalesforceSchoolLoan(ctx context.Context, tx pgx.Tx, loanID string) error {
	var status string
	var reference *string
	err := tx.QueryRow(ctx, `SELECT salesforce_status, salesforce_loan_id FROM bt_mfi_loan WHERE id = $1 AND deleted_at IS NULL`,
		loanID).Scan(&status, &reference)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("integrationsync: reading the school loan: %w", err)
	}
	if status != "confirmed" || reference == nil || *reference == "" {
		return errNoLoanReference
	}
	return referenceNotConfigured(salesforce, "school_loan", *reference)
}

// NetSuiteFacilityTranche is `integrations.netsuite.facility_tranche`.
func NetSuiteFacilityTranche(ctx context.Context, tx pgx.Tx, trancheID string) error {
	var live, synced bool
	err := tx.QueryRow(ctx, `SELECT
  EXISTS (SELECT 1 FROM bt_funding_facility_tranche t WHERE t.id = $1
          AND NOT EXISTS (SELECT 1 FROM bt_funding_facility_tranche_reversal r WHERE r.tranche_id = t.id)),
  EXISTS (SELECT 1 FROM integration_sync WHERE system = 'netsuite' AND context_type = 'facility_tranche'
          AND context_id = $1 AND status IN ('succeeded', 'reconciled_manual'))`, trancheID).Scan(&live, &synced)
	if err != nil {
		return fmt.Errorf("integrationsync: reading the facility tranche: %w", err)
	}
	if !live || synced {
		return nil
	}
	return notConfigured(netsuite)
}

// NetSuiteAdvance is `integrations.netsuite.advance`.
func NetSuiteAdvance(ctx context.Context, tx pgx.Tx, advanceID string, now time.Time) error {
	var reference *string
	err := tx.QueryRow(ctx, `SELECT accountability_netsuite_id FROM advance_request WHERE id = $1`, advanceID).Scan(&reference)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("integrationsync: reading the advance: %w", err)
	}
	if reference != nil && *reference != "" {
		return record(ctx, tx, netsuite, "advance", advanceID, *reference, now)
	}
	return notConfigured(netsuite)
}

// record is _record for a reconciled reference: the record's one ledger row.
func record(ctx context.Context, tx pgx.Tx, system, contextType, contextID, externalID string, now time.Time) error {
	if _, err := tx.Exec(ctx, `
INSERT INTO integration_sync (id, created_at, updated_at, system, context_type, context_id, external_id, status,
  last_error, synced_at)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, '', $2)
ON CONFLICT (system, context_type, context_id) DO UPDATE SET status = EXCLUDED.status,
  external_id = EXCLUDED.external_id, last_error = '', synced_at = EXCLUDED.synced_at, updated_at = EXCLUDED.updated_at`,
		cuid.New(), now, system, contextType, contextID, externalID, reconciled); err != nil {
		return fmt.Errorf("integrationsync: recording the %s sync: %w", system, err)
	}
	return nil
}
