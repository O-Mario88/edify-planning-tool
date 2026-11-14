package ownership

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestTheHistoryReadsBatchesThenSchoolTransfers(t *testing.T) {
	admin := auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}
	day := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	r := page(admin,
		[]moved{{districtID: "d1", district: "Abim", to: "Sarah", decision: "transfer", reason: "Rebalance  load", effective: day, count: 3, activities: 2}},
		[]moved{{schoolCode: "1000", school: "Central", to: "Sarah", decision: "keep", effective: day, activities: 1}},
		nil, url.Values{})
	if len(r.Blocks) != 3 || r.Blocks[0].GetPanel().Title != "Reassign District Portfolio Owner" {
		t.Fatalf("blocks: %v", r.Blocks)
	}
	rows := r.Blocks[2].GetTable().Rows
	if c := rows[0].Cells; c[0].Text != "3 schools · Abim" || c[0].Href != "/districts/d1" || c[1].Text != "Unassigned" ||
		c[4].Text != "Transfer eligible open activities to the new owner · 2 moved" || c[5].Text != "Rebalance load" {
		t.Errorf("batch row: %v", c)
	}
	if c := rows[1].Cells; c[0].Href != "/schools/1000" || c[3].Text != "1 Nov 2026" || c[4].Text != "Keep open activities with their current owner · 1 moved" {
		t.Errorf("transfer row: %v", c)
	}
	empty := page(admin, nil, nil, nil, url.Values{}).Blocks[2].GetTable()
	if empty.EmptyMessage != "No ownership transfer has been recorded yet." {
		t.Errorf("empty: %v", empty)
	}
}

func TestAPreviewIsCountedByTheExistingApplication(t *testing.T) {
	s := &Service{}
	_, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}, Path,
		url.Values{"district": {"d1"}, "from_staff": {"sp1"}})
	if served || err != nil {
		t.Errorf("served %v, err %v", served, err)
	}
}
