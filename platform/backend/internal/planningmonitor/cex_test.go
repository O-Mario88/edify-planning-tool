package planningmonitor

import (
	"testing"
	"time"
)

// buckets_for: a month's four weeks (the last taking the rest), a quarter's
// months, a year's quarters from October.
func TestCEXBuckets(t *testing.T) {
	month := cexBuckets(cpoWindowFor("2027", "month", "", 11, nil))
	if len(month) != 4 || month[0].caption != "1–7 Nov" || month[3].caption != "22–30 Nov" || month[3].end.Format("2006-01-02") != "2026-12-01" {
		t.Errorf("month %v", month)
	}
	quarter := cexBuckets(cpoWindowFor("2027", "quarter", "Q2", 0, nil))
	if len(quarter) != 3 || quarter[0].label != "Jan" || quarter[0].caption != "2027" {
		t.Errorf("quarter %v", quarter)
	}
	year := cexBuckets(cpoWindowFor("2027", "fy", "", 0, nil))
	if len(year) != 4 || year[0].caption != "Oct–Dec" || year[3].label != "Q4" {
		t.Errorf("year %v", year)
	}
	d := func(s string) *time.Time { v, _ := time.Parse("2006-01-02", s); return &v }
	if cexBucketOf(d("2026-10-31"), month) != -1 || cexBucketOf(d("2026-11-08"), month) != 1 || cexBucketOf(nil, month) != 4 {
		t.Error("bucket_of")
	}
}

// classify: work past its day waits on whoever holds the next step — the
// implementer, Finance where money is not disbursed, the school where it is
// closed, the Lead or IA — and verified work's closure is Finance's while a
// Partner is unpaid.
func TestCEXClassify(t *testing.T) {
	today := date(2026, 11, 25)
	due := date(2026, 11, 20)
	start := date(2026, 11, 21)
	cases := []struct {
		in                    cexInput
		stage, overdue, owner string
		timing                string
	}{
		{cexInput{status: "scheduled", due: &due, today: today, schoolOperating: true}, "scheduled", "execution", "staff", "not_started"},
		{cexInput{status: "scheduled", due: &due, today: today, schoolOperating: true, fundsPending: true}, "scheduled", "execution", "finance", "not_started"},
		{cexInput{status: "scheduled", due: &due, today: today}, "scheduled", "execution", "external", "not_started"},
		{cexInput{status: "in_progress", partner: true, due: &due, start: &start, today: today, schoolOperating: true}, "in_field", "evidence", "partner", "late"},
		{cexInput{status: "submitted_to_pl", due: &due, start: &due, today: today}, "pl_review", "pl_review", "pl", "on_time"},
		{cexInput{status: "awaiting_ia_verification", due: &due, today: today}, "ia_review", "ia_review", "ia", "unknown"},
		{cexInput{status: "ia_verified", due: &due, today: today, closureOwner: "finance"}, "verified", "", "finance", "unknown"},
		{cexInput{status: "cancelled", due: &due, today: today}, "cancelled", "", "", "cancelled"},
	}
	for _, c := range cases {
		s := cexClassify(c.in)
		if s.stage != c.stage || s.overdue != c.overdue || s.owner != c.owner || s.timing != c.timing {
			t.Errorf("%s: %+v", c.in.status, s)
		}
	}
	if s := cexClassify(cases[0].in); s.age != 5 || cexAgeGroup(s.age) != "age_3_7" {
		t.Errorf("age %d", s.age)
	}
}

// _pager.html is an edify-pagination-scope: the feed reads it as a pager of
// its own whose count line is a page without a link, and only when there is
// more than one page.
func TestCEXPagerReadsAsScopedPager(t *testing.T) {
	s := &cexSnapshot{filters: cexFilters{fy: "2027", period: "fy"}}
	if s.pagerNodes("school", 40, 1, 1) != nil {
		t.Fatal("a single page draws no pager")
	}
	blocks := walk(el("div", "", s.pagerNodes("school", 120, 2, 3)))
	if len(blocks) != 1 || blocks[0].GetPager() == nil {
		t.Fatalf("blocks %v", blocks)
	}
	pages := blocks[0].GetPager().GetPages()
	if len(pages) != 3 || pages[0].GetLabel() != "120 in all · page 2 of 3" || pages[0].GetHref() != "" ||
		pages[1].GetLabel() != "Previous" || pages[2].GetHref() != cexBase+"/table?table=school&view=execution&fy=2027&period=fy&page=3" {
		t.Errorf("pages %v", pages)
	}
}
