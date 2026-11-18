//go:build integration

package integration

import (
	"context"
	"strconv"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/disbursements"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The country through advances (docs/migration/80-multi-country-phase-0.md
// §19). With Kenya Active and keeping its money in KES, a Kenyan and a
// Ugandan monthly fund plan awaiting disbursement, and an officer who is
// Accountant in Kenya alone: Kenya's Disbursement dashboard holds Kenya's
// plan alone, in KES, and Uganda's holds Uganda's alone, in UGX. Every row
// the test files starts "gcad".
func TestTheCountryThroughAdvances(t *testing.T) {
	ctx := context.Background()
	accountant, officer, exec := twoKenyans(t, "gcad")
	exec(`INSERT INTO country_registry.country_role_assignment (id, membership_id, country_id, user_id, role_name, scope_type, granted_by, grant_reason)
SELECT gen_random_uuid(), m.id, m.country_id, m.user_id, 'Accountant', 'country', 'gcad', 'Country test'
FROM country_registry.country_membership m WHERE m.user_id = $1 AND m.granted_by = 'gcad'`, accountant.user)
	exec(`INSERT INTO country_registry.country_config_version
  (id, country_id, version, default_language, languages, currency_code, currency_minor_units, time_zone, date_format,
   calendars, fy_start_month, effective_from, changed_by, change_reason)
SELECT gen_random_uuid(), id, 1, 'en', '{en,sw}', 'KES', 0, 'Africa/Nairobi', 'j M Y', '{gregorian}', 7, current_date - 1, 'gcad', 'gcad settings'
FROM country_registry.country WHERE code = 'KE'`)

	var ugandan, ugandaAccountant string
	if err := admin.QueryRow(ctx, `SELECT (SELECT u.id FROM "user" u WHERE u.active_role = 'CCEO' AND u.is_active AND u.id <> ALL($1) ORDER BY u.id LIMIT 1),
  (SELECT id FROM "user" WHERE email = 'accountant@edify.org')`, []string{accountant.user, officer.user}).Scan(&ugandan, &ugandaAccountant); err != nil {
		t.Fatalf("a Ugandan officer and accountant: %v", err)
	}
	now := time.Now()
	fy := schooldirectory.OperationalFY(now)
	month := int(now.In(mustNairobi(t)).Month())
	for _, plan := range []struct {
		id, owner string
		amount    int64
	}{{"gcad-ke", officer.user, 77777}, {"gcad-ug", ugandan, 88888}} {
		exec(`INSERT INTO fund_request (created_at, updated_at, id, fy, period, period_key, scope, submitted_by_user_id, submitted_by_role,
  total_amount, activity_count, status)
VALUES (now(), now(), $1, $2, 'monthly', $3, 'self', $4, 'CCEO', $5, 1, 'submitted')`,
			plan.id, fy, fy+"-M"+strconv.Itoa(month), plan.owner, plan.amount)
	}

	dashboard := func(user, role string) string {
		t.Helper()
		page, err := pageOf(token(t, user, role, time.Hour), disbursements.PagePath,
			map[string]string{"fy": fy, "month": strconv.Itoa(month)})
		if err != nil {
			t.Fatalf("the Disbursement dashboard as %s: %v", role, err)
		}
		return protojson.Format(page)
	}
	inKenya, inUganda := dashboard(accountant.user, "Accountant"), dashboard(ugandaAccountant, "Accountant")
	// The compact form rounds thousands to whole ones: 77,777 is "78K".
	if !strings.Contains(inKenya, "KES 78K") || strings.Contains(inKenya, "89K") || strings.Contains(inKenya, "UGX") {
		t.Error("Kenya's dashboard does not hold exactly Kenya's plan in KES")
	}
	if !strings.Contains(inUganda, "UGX 89K") || strings.Contains(inUganda, "78K") || strings.Contains(inUganda, "KES") {
		t.Error("Uganda's dashboard does not hold exactly Uganda's plan in UGX")
	}
}
