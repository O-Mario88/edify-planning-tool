package dbguard

import (
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

func TestCheckDSN(t *testing.T) {
	tests := []struct {
		name    string
		policy  Policy
		dsn     string
		refused string // substring of the refusal; empty means allowed
	}{
		{
			name:   "development on localhost",
			policy: Policy{Env: config.Development},
			dsn:    "postgresql://edify_gateway@localhost:5432/edify_gorn_dev",
		},
		{
			name:   "development on loopback address",
			policy: Policy{Env: config.Development},
			dsn:    "postgresql://edify_gateway@127.0.0.1:5432/edify_gorn_dev",
		},
		{
			name:   "test over a unix socket",
			policy: Policy{Env: config.Test},
			dsn:    "host=/tmp dbname=edify_gorn_test user=edify_gateway",
		},
		{
			name:    "production environment is never allowed",
			policy:  Policy{Env: config.Production},
			dsn:     "postgresql://localhost/edify",
			refused: "may not run against production",
		},
		{
			name:    "the production cluster name is refused",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://u:p@edify-production-db-do-user-1.b.db.ondigitalocean.com:25060/defaultdb?sslmode=require",
			refused: "production marker",
		},
		{
			name:    "the production marker is refused even when allow-listed",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"edify-production-db.example.com"}},
			dsn:     "postgresql://u:p@edify-production-db.example.com/db?sslmode=require",
			refused: "production marker",
		},
		{
			name:    "a configured production hostname is refused",
			policy:  Policy{Env: config.Development, ProductionMarkers: []string{"db-live-01"}},
			dsn:     "postgresql://u:p@DB-LIVE-01.internal/db",
			refused: "production marker",
		},
		{
			name:    "a production marker in the database name is refused",
			policy:  Policy{Env: config.Development, ProductionMarkers: []string{"edify_live"}},
			dsn:     "postgresql://localhost/edify_live",
			refused: "production marker",
		},
		{
			name:    "development may not reach a remote host",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://u:p@10.20.0.5:5432/edify",
			refused: "not in EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name:    "a remote fallback host is refused",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://u:p@localhost:5432,remote.example.com:5432/edify",
			refused: "not in EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name:    "staging never falls back to localhost",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@localhost/edify?sslmode=require",
			refused: "not in EDIFY_DB_ALLOWED_HOSTS",
		},
		{
			name:    "staging requires TLS",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@staging-db.internal/edify?sslmode=disable",
			refused: "must use TLS",
		},
		{
			name:    "staging refuses a URL that may fall back to plain text (no sslmode means prefer)",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@staging-db.internal/edify",
			refused: "must use TLS",
		},
		{
			name:    "staging refuses sslmode=prefer",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@staging-db.internal/edify?sslmode=prefer",
			refused: "must use TLS",
		},
		{
			name:    "staging refuses sslmode=allow",
			policy:  Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:     "postgresql://u:p@staging-db.internal/edify?sslmode=allow",
			refused: "must use TLS",
		},
		{
			name:   "staging accepts sslmode=verify-full",
			policy: Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:    "postgresql://u:p@staging-db.internal/edify?sslmode=verify-full",
		},
		{
			name:   "staging on its named host with TLS",
			policy: Policy{Env: config.Staging, AllowedHosts: []string{"staging-db.internal"}},
			dsn:    "postgresql://u:p@staging-db.internal/edify?sslmode=require",
		},
		{
			name:    "an unparseable URL is refused without echoing it",
			policy:  Policy{Env: config.Development},
			dsn:     "postgresql://user:s3cret@localhost:notaport/db",
			refused: "could not be parsed",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := CheckDSN(test.policy, test.dsn)
			if test.refused == "" {
				if err != nil {
					t.Fatalf("unexpected refusal: %v", err)
				}
				return
			}
			if !errors.Is(err, ErrRefused) {
				t.Fatalf("want ErrRefused, got %v", err)
			}
			if !strings.Contains(err.Error(), test.refused) {
				t.Fatalf("want refusal containing %q, got %v", test.refused, err)
			}
			if strings.Contains(err.Error(), "s3cret") {
				t.Fatalf("the refusal leaks the password: %v", err)
			}
		})
	}
}

// The gateway never writes to or changes the existing application's schema.
// This test fails the build if a write, a DDL statement or an ORM
// auto-migration call appears in its sources, with sanctioned exceptions for
// the Go-owned schemas only:
//
//   - inside internal/clusterlead a write may target only cluster_leadership
//     tables, and inside internal/loans only school_loans tables;
//   - DDL appears only in internal/ownedschema, the shared migration
//     mechanics, and only on a schema's own migration ledger
//     (%s.schema_migration, %s being the schema's checked name);
//   - nothing anywhere may remove a table, its rows or its data.
func TestGatewaySourcesContainNoSchemaChanges(t *testing.T) {
	forbidden := regexp.MustCompile(
		`(?i)\b(CREATE|ALTER|DROP|TRUNCATE)\s+(TABLE|INDEX|SCHEMA|DATABASE|SEQUENCE|TRIGGER)\b|AutoMigrate|\bINSERT\s+INTO\b|\bUPDATE\s+\S+\s+SET\b|\bDELETE\s+FROM\b`,
	)
	root := filepath.Join("..", "..")
	sep := string(filepath.Separator)
	// Where a write may appear, and the schema it must name.
	writers := map[string]string{
		filepath.Join(root, "internal", "clusterlead") + sep: "cluster_leadership.",
		filepath.Join(root, "internal", "loans") + sep:       "school_loans.",
		// Location reports and captures: field_routes only, never the
		// existing school coordinates (owner, 2026-11-14).
		filepath.Join(root, "internal", "routeplan") + sep: "field_routes.",
		// Edify Global's registry (docs/migration/80 §8): the legacy seed and
		// the country settings API, under the registry's row-level security.
		filepath.Join(root, "internal", "country") + sep:       "country_registry.",
		filepath.Join(root, "internal", "countryconfig") + sep: "country_registry.",
	}
	// Signing in and account administration, which Go owns (owner brief,
	// 2026-11-11), write the existing account tables, and the audit chain
	// appends to the existing log: those packages and tables only, never a
	// removal or DDL. The
	// database role enforces the same columns (deploy/db/identity_roles.sql).
	existingWriters := map[string][]string{
		filepath.Join(root, "internal", "signin") + sep: {
			`"user"`, "refresh_token", "mfa_challenge", "user_invitation", "staff_profile", "login_event",
		},
		filepath.Join(root, "internal", "audit") + sep: {"audit_log", "domain_event_log"},
		filepath.Join(root, "internal", "accounts") + sep: {
			`"user"`, "refresh_token", "user_invitation", "staff_profile", "staff_geography_assignment",
		},
		filepath.Join(root, "internal", "teams") + sep: {
			"staff_supervisor_assignment", "partner_member", "partner_school_member", "activity",
		},
		// Acting appointments, and the account's acting hint and role in use.
		filepath.Join(root, "internal", "acting") + sep: {"acting_assignment", `"user"`},
		// Scheduling a school visit, the first Go save (docs/migration/27;
		// deploy/db/activities_roles.sql): the activity, its day, the costs
		// to follow, the ledger's mark and the recommendation it answers;
		// and moving one (docs/migration/29): its timeline row; and a
		// cluster's Group Training (docs/migration/38): its invitations.
		filepath.Join(root, "internal", "activities") + sep: {
			"activity", "daily_visit_batch", "daily_visit_costs_to_follow", "target_ledger_dirty", "ssa_recommendation",
			"activity_schedule_change", "cluster_activity_attendance", "activity_cost_snapshot",
			// An item's version 1, written the first time it is scheduled.
			"activity_catalogue_version",
			// A Core school's visit takes one of its package's slots.
			"core_activity_slot", "core_plan",
			// The Core Schools form's hand-over to a partner.
			"partner_assignment",
		},
		// Snoozing a To-Do from Today (docs/migration/50;
		// deploy/db/todo_roles.sql): the person's snooze row.
		filepath.Join(root, "internal", "todosnooze") + sep: {"command_center_todo_snooze"},
		// The Daily Debrief (apps.debriefs.field_debrief_service
		// DailyDebriefFlowService): the day's row, its work and who it is
		// routed to.
		// Extra Assigned Work (apps.hr.extra_work): the assignment's row.
		filepath.Join(root, "internal", "extrawork") + sep: {"hr_extra_assignment"},
		// A Most Significant Change Story submitted from My Targets
		// (staff_views.mscs_submit_view; deploy/db/mscs_roles.sql).
		filepath.Join(root, "internal", "mscs") + sep: {"mscs_story"},
		// The PD reminders job moves the course clock and logs each reminder
		// (apps.professional_development.reminders).
		// and the document lifecycle (apps.documents.jobs).
		filepath.Join(root, "internal", "notificationjobs") + sep: {"pd_request", "pd_reminder_log", "document_asset d",
			"document_acknowledgement", "document_engagement_session"},
		// The HR programmes' forms (apps.frontend.views.hr_programme_views):
		// recognitions, compliance requirements and evidence, pulse surveys,
		// safety incidents, offboardings, employee-relations cases, formal
		// plans, vacancies, candidates and applications.
		filepath.Join(root, "internal", "hrforms") + sep: {"hr_staff_recognition", "hr_compliance_requirement",
			"hr_employee_compliance_record", "hr_pulse_survey", "hr_safety_incident", "hr_offboarding", "hr_relations_case",
			"hr_pip_plan", "hr_vacancy", "hr_candidate", "hr_application", "hr_compensation", "pd_request"},
		// Team Coaching's saves (apps.cce_leadership.coaching).
		filepath.Join(root, "internal", "ccelead") + sep: {"cce_cceo_coaching", "cce_regional_engagement", "cce_regional_report"},
		// The Measurement Framework's saves (apps.impact.framework).
		filepath.Join(root, "internal", "iaframework") + sep: {"impact_outcome_area", "impact_outcome_area_domain",
			"impact_indicator_definition", "bt_loan_purpose"},
		// School Evidence's saves (apps.impact.evidence_services).
		filepath.Join(root, "internal", "schoolevidence") + sep: {"impact_learning_result", "impact_discipleship_record",
			"impact_edtech_deployment", "impact_edtech_check"},
		// The Staff Activity follow-ups (apps.staff_activity.follow_ups).
		filepath.Join(root, "internal", "staffactivity") + sep: {"staff_usage_follow_up"},
		// The weekly sample checks (apps.activities.verification_sampling).
		filepath.Join(root, "internal", "iasampling") + sep: {"ia_verification_sample"},
		filepath.Join(root, "internal", "debriefs") + sep: {
			"daily_debrief", "daily_debrief_activity_link", "daily_debrief_recipient",
			// The scheduler's recurring-issue scan (insight_service): its insights.
			"daily_debrief_insight",
			// The scheduler's weekly team reports (weekly_report_service).
			"weekly_debrief_report",
		},
		// My Professional Development's read writes what the existing read
		// writes (owner, 2026-11-16: "Same writes"; docs/migration/68 §68.7;
		// deploy/db/mypd_roles.sql): a course moved on by its dates and the
		// year's allocation; its reminders close through a narrow function.
		filepath.Join(root, "internal", "mypd") + sep: {"pd_request", "pd_allocation"},
		// The outbox's Business Transformation handlers (apps.business_
		// transformation.handlers; deploy/db/activities_roles.sql): a verified
		// SSA's case, trigger, recommendations and the year's policy, insert
		// only; a loan-use verification's requirement and result following
		// the visit's IA state.
		filepath.Join(root, "internal", "btcases") + sep: {
			"bt_policy", "bt_case", "bt_case_trigger", "bt_case_recommendation",
			"bt_loan_verification_requirement", "bt_loan_use_result",
			// The scheduler's loan tracking: its permanent delivery log.
			"bt_loan_tracking_delivery_log",
		},
		// The outbox's Special Project handlers (apps.projects.baselines and
		// handlers; deploy/db/activities_roles.sql): an enrolment's baseline,
		// verdict, follow-up and stamped rule, never a new or removed one.
		filepath.Join(root, "internal", "projectimpact") + sep: {"project_school_assignment"},
		// The outbox's Salesforce and NetSuite handlers (apps.integrations;
		// deploy/db/activities_roles.sql): a reconciled reference's ledger row.
		filepath.Join(root, "internal", "integrationsync") + sep: {"integration_sync"},
		// The outbox's email copies (apps.notifications.email_delivery): a
		// copy's status as it is sent or why it was not.
		filepath.Join(root, "internal", "notifymail") + sep: {"notification_delivery"},
		// The outbox's notification.push (apps.notifications.push): the copy's
		// status and the device's health; nothing inserted or removed.
		filepath.Join(root, "internal", "pushdelivery") + sep: {"notification_delivery", "notification_push_subscription"},
		// The scheduler's target_ledger_sync (apps.targets): the stored
		// achievement ledger, rebuilt; no row removed.
		filepath.Join(root, "internal", "targets") + sep: {"target_achievement_ledger"},
		// The scheduler's data_quality_scan (apps.schools.data_quality): the
		// duplicate pairs it proposes and the quality issues it reconciles.
		filepath.Join(root, "internal", "dataqualityscan") + sep: {"school_duplicate_candidate", "data_quality_issue"},
		// The scheduler's interaction_rollup (apps.telemetry): one row a
		// person a day.
		filepath.Join(root, "internal", "telemetryrollup") + sep: {"interaction_day"},
		// The scheduler's admin_maintenance_generation (apps.admin_ops): a due
		// template's work item, and the template's next due day.
		filepath.Join(root, "internal", "adminops") + sep: {"admin_ops_work_item", "admin_maintenance_template"},
		// The scheduler's closure_checklist_refresh (closure_services): each
		// open activity's stored checklist and blockers.
		filepath.Join(root, "internal", "closurepages") + sep: {"closure_checklist", "closure_blocker"},
		// The scheduler's autopilot_weekly_proposals (apps.autopilot): next
		// week's drafts and their proposed visits.
		filepath.Join(root, "internal", "autopilotjobs") + sep: {"autopilot_proposed_plan", "autopilot_proposed_activity"},
	}
	mechanics := filepath.Join(root, "internal", "ownedschema") + sep
	// The lint describes the DDL it allows as patterns; it runs none.
	lint := filepath.Join(root, "internal", "ownedschema", "lint.go")
	removes := func(statement string) bool {
		upper := strings.ToUpper(statement)
		return strings.Contains(upper, "DROP") || strings.Contains(upper, "TRUNCATE") ||
			strings.Contains(upper, "DELETE") || strings.Contains(upper, "AUTOMIGRATE")
	}
	targetOf := func(source []byte, match []int) string {
		statement := string(source[match[0]:match[1]])
		if strings.HasPrefix(strings.ToUpper(statement), "UPDATE") {
			return strings.TrimSpace(statement[len("UPDATE"):])
		}
		after := strings.TrimSpace(string(source[match[1]:]))
		for _, filler := range []string{"IF NOT EXISTS", "IF EXISTS", "ONLY"} {
			if strings.HasPrefix(strings.ToUpper(after), filler) {
				after = strings.TrimSpace(after[len(filler):])
			}
		}
		return after
	}
	// The one removal allowed: team link rows the existing code itself
	// deletes when a reporting line or a school split changes, and a roster
	// entry removed (apps/accounts/supervisor_service.py, apps/partners). The
	// role grants DELETE on these three tables and no other.
	teamsDir := filepath.Join(root, "internal", "teams") + sep
	removableLinks := []string{"staff_supervisor_assignment", "partner_member", "partner_school_member"}
	allowed := func(path string, source []byte, match []int) bool {
		statement := string(source[match[0]:match[1]])
		if removes(statement) {
			if !strings.HasPrefix(path, teamsDir) || !strings.HasPrefix(strings.ToUpper(statement), "DELETE FROM") {
				return false
			}
			target := targetOf(source, match)
			for _, table := range removableLinks {
				if strings.HasPrefix(target, table+" ") {
					return true
				}
			}
			return false
		}
		target := targetOf(source, match)
		if strings.HasPrefix(path, mechanics) {
			return strings.HasPrefix(target, "%s.schema_migration")
		}
		isDDL := regexp.MustCompile(`(?i)^(CREATE|ALTER)`).MatchString(statement)
		for dir, schema := range writers {
			if strings.HasPrefix(path, dir) && !isDDL {
				return strings.HasPrefix(strings.ToLower(target), schema)
			}
		}
		for dir, tables := range existingWriters {
			if !strings.HasPrefix(path, dir) || isDDL {
				continue
			}
			for _, table := range tables {
				if strings.HasPrefix(target, table+" ") || strings.HasPrefix(target, table+"(") {
					return true
				}
			}
		}
		return false
	}
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if entry.Name() == "gen" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		source, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if path == lint {
			return nil
		}
		for _, match := range forbidden.FindAllIndex(source, -1) {
			if !allowed(path, source, match) {
				t.Errorf("%s contains a write or schema statement: %q", path, string(source[match[0]:match[1]]))
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
