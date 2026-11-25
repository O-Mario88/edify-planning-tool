package escalations

// raise_escalation: a raiser puts a decision in front of the level above
// them, addressed to their supervisor holding that level's role when the
// reporting line names one, else to the role in their country.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// RaiseError is raise_escalation's BadRequest or Forbidden, in its words.
type RaiseError struct{ Message string }

func (e *RaiseError) Error() string { return e.Message }

// Raise is raise_escalation's data and its raiser.
type Raise struct {
	RaiserID, RaiserRole, RaiserName   string
	Category, Severity                 string
	Subject, Detail, RequestedDecision string
	ScopeType, ScopeID, ScopeName      string
	Origin                             activities.Origin
}

// Raised is the escalation written and the level it is addressed to, in
// words ("Country Director").
type Raised struct{ ID, AddressedTo string }

// RaiseIn writes r in tx as raise_escalation does. A refusal is a
// *RaiseError.
func RaiseIn(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, r Raise) (Raised, error) {
	level := rules.Roles[r.RaiserRole].RaisesTo
	if level == "" {
		return Raised{}, &RaiseError{"Only field staff, Programme Leads and the Country Director may escalate."}
	}
	subject, detail := strings.TrimSpace(r.Subject), strings.TrimSpace(r.Detail)
	if subject == "" {
		return Raised{}, &RaiseError{"A subject is required."}
	}
	if detail == "" {
		return Raised{}, &RaiseError{fmt.Sprintf("Describe what the %s needs to decide.", addresseeLabel(level))}
	}
	category := strings.TrimSpace(first(r.Category, "other"))
	if _, ok := lookup(rules.Categories, category); !ok {
		return Raised{}, &RaiseError{"Unknown escalation category."}
	}
	severity := strings.TrimSpace(first(r.Severity, rules.DefaultSeverity))
	if _, ok := lookup(rules.Severities, severity); !ok {
		return Raised{}, &RaiseError{"Unknown severity."}
	}
	assignee := ""
	if level != rules.RegionalLevel {
		var err error
		if assignee, _, err = supervisorOf(ctx, tx, r.RaiserID, rules.RoleForAddressee[level]); err != nil {
			return Raised{}, err
		}
	}
	var country *string
	if err := tx.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`,
		r.RaiserID).Scan(&country); err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return Raised{}, fmt.Errorf("escalations: the raiser's country: %w", err)
	}
	countryID := "Uganda"
	if country != nil && *country != "" {
		countryID = *country
	}
	id := cuid.New()
	if _, err := tx.Exec(ctx, `INSERT INTO leadership_escalation (created_at, updated_at, id, raised_by_user_id, raised_by_name,
  addressed_role, assigned_to_user_id, country_id, category, subject, detail, requested_decision, severity, scope_type, scope_id,
  scope_name, due_date, status)
VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NULL, $16)`,
		now, id, r.RaiserID, r.RaiserName, level, orNil(assignee), countryID, category, cut(subject, 255), detail,
		orNil(cut(strings.TrimSpace(r.RequestedDecision), 512)), severity, orNil(strings.TrimSpace(r.ScopeType)),
		orNil(strings.TrimSpace(r.ScopeID)), orNil(strings.TrimSpace(r.ScopeName)), rules.Statuses.Open); err != nil {
		return Raised{}, fmt.Errorf("escalations: writing the escalation: %w", err)
	}
	raised := Raised{ID: id, AddressedTo: addresseeLabel(level)}
	tellRaised(ctx, tx, push, now, raised, Addressed{ID: id, Severity: severity, Level: level, Assigned: assignee, Country: countryID,
		Detail: detail}, r.RaiserName, cut(subject, 255))
	cover, err := audit.CoverageStamp(ctx, tx, r.RaiserID, now)
	if err != nil {
		return Raised{}, err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{Action: "escalation_raise", SubjectKind: audit.Text("LeadershipEscalation"),
		SubjectID: audit.Text(id), ActorID: audit.Text(r.RaiserID), ActorRole: audit.Text(r.RaiserRole), Success: true,
		IPAddress: audit.Text(r.Origin.IP), UserAgent: audit.Text(r.Origin.UserAgent), CorrelationID: audit.Text(r.Origin.CorrelationID),
		Payload: audit.WithStamps(map[string]any{"subject": cut(subject, 255), "category": category, "severity": severity,
			"addressedRole": level, "assignedTo": orNil(assignee)}, cover)}, now); err != nil {
		return Raised{}, fmt.Errorf("escalations: auditing the escalation: %w", err)
	}
	return raised, nil
}

// cut is a Python slice [:n].
func cut(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

func orNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func first(s, otherwise string) string {
	if s == "" {
		return otherwise
	}
	return s
}
