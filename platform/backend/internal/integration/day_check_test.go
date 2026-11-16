//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
)

// The day check a save asks before it opens its transaction, answered by Go
// (pricing.DayCheck) as the existing probe answers it (gateway_relay._probe,
// played and rolled back): the refusal, where it is met, whether the day
// pools the visit, whether it is an online training. Over a visit joining
// days whose transport was paid, whose members' money has moved or is held
// by a weekly or monthly request, whose card lacks a rate, a locked week,
// every catalogue item and every member of staff. Skipped unless
// EDIFY_CHECK_ORACLE names a file internal/pricing/testdata/check_oracle.py
// wrote today.
func TestGoAnswersTheDayCheckAsTheExistingProbe(t *testing.T) {
	path := os.Getenv("EDIFY_CHECK_ORACLE")
	if path == "" {
		t.Skip("EDIFY_CHECK_ORACLE is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Today     string                       `json:"today"`
		Rows      map[string][]json.RawMessage `json:"rows"`
		Proposals []struct {
			ID      string `json:"id"`
			Error   string `json:"error"`
			Refusal string `json:"refusal"`
			Stage   string `json:"stage"`
			Pooled  bool   `json:"pooled"`
			Online  bool   `json:"online"`
			Fields  struct {
				ActivityType string  `json:"activity_type"`
				Mode         *string `json:"programme_delivery_mode"`
				School       *string `json:"school_id"`
				Cluster      *string `json:"cluster_id"`
				Responsible  string  `json:"responsible_staff_id"`
				Item         string  `json:"catalogue_item_id"`
				PlannedDate  string  `json:"planned_date"`
				Expected     *int    `json:"expected_participants"`
				Printing     *int    `json:"printing_pages"`
				PhotoPages   *int    `json:"photocopy_pages"`
				PhotoCopies  *int    `json:"photocopy_copies"`
			} `json:"fields"`
		} `json:"proposals"`
	}
	if err := json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	if oracle.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the oracle was written on %s", oracle.Today)
	}
	ctx := context.Background()
	// Children first.
	tables := []string{"fund_request_item", "weekly_fund_request_line", "advance_request", "transport_payment",
		"activity_schedule_cost_line", "fund_request", "weekly_fund_request",
		"activity", "daily_visit_batch", "cost_setting", "cost_catalogue"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gpc%' OR id LIKE 'gpd%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for i := len(tables) - 1; i >= 0; i-- {
		table := tables[i]
		for _, row := range oracle.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	str := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	asked, differing := 0, 0
	for _, want := range oracle.Proposals {
		if want.Error != "" {
			t.Logf("%s: the probe failed (%s); not asked", want.ID, want.Error)
			continue
		}
		f := want.Fields
		planned, err := time.Parse(time.DateOnly, f.PlannedDate)
		if err != nil {
			t.Fatal(err)
		}
		got, err := pricing.DayCheck(ctx, gateway, pricing.Proposed{
			ID: want.ID, ActivityType: f.ActivityType, Mode: str(f.Mode), SchoolID: str(f.School),
			ClusterID: str(f.Cluster), ResponsibleStaffID: f.Responsible, CatalogueItemID: f.Item,
			PlannedDate: &planned, ExpectedParticipants: f.Expected,
			PrintingPages: f.Printing, PhotocopyPages: f.PhotoPages, PhotocopyCopies: f.PhotoCopies,
		})
		if err != nil {
			t.Fatalf("%s: %v", want.ID, err)
		}
		asked++
		if got.Refusal != want.Refusal || got.Stage != want.Stage || got.Pooled != want.Pooled || got.Online != want.Online {
			differing++
			if differing <= 5 {
				t.Errorf("%s differs\n go:       %+v\n existing: refusal=%q stage=%q pooled=%v online=%v",
					want.ID, got, want.Refusal, want.Stage, want.Pooled, want.Online)
			}
		}
	}
	t.Logf("%d saves asked, %d differing", asked, differing)
}
