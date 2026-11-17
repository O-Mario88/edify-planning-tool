package prioritiesmaster

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func str(s string) *string { return &s }

// The target column words a figure as _target_display and _fmt_number do.
func TestTheTargetIsWordedAsTheViewWordsIt(t *testing.T) {
	due := time.Date(2026, time.September, 30, 0, 0, 0, 0, time.UTC)
	cases := []struct {
		name string
		ms   milestone
		want string
	}{
		{"a count with its unit", milestone{target: str("12212.00"), unit: "visits"}, "12,212 visits"},
		{"a fraction keeps its places", milestone{target: str("1234.50"), unit: "loans"}, "1,234.50 loans"},
		{"a rate", milestone{target: str("60.00"), measurement: "percentage", unit: "percent"}, "60%"},
		{"a monthly recurrence", milestone{recurrence: str("2"), unit: "posts"}, "2 posts per month"},
		{"a recurrence without a unit", milestone{recurrence: str("4")}, "4 times per month"},
		{"a zero recurrence is none", milestone{recurrence: str("0"), target: str("5")}, "5"},
		{"a date", milestone{measurement: "date", due: &due}, "by 30 Sep 2026"},
		{"a date from the source", milestone{measurement: "date", targetSourceText: "Q4"}, "Q4"},
		{"NA in the source", milestone{targetSourceText: "Audit — NA"}, "NA"},
		{"NA at the end of the text", milestone{sourceText: "Board meetings NA  "}, "NA"},
		{"an assessment's words", milestone{measurement: "qualitative", targetSourceText: "Culture — Strong"}, "Strong"},
		{"nothing", milestone{}, "—"},
	}
	for _, c := range cases {
		if got := c.ms.targetDisplay(); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
	}
	ms := milestone{unit: "schools"}
	if got := ms.held(&holding{value: "50.00", draft: true}); got != "50 schools draft" {
		t.Errorf("a draft holding: %q", got)
	}
	if got := ms.held(nil); got != "—" {
		t.Errorf("no holding: %q", got)
	}
}

// The roles that run the master are sent on with the ask as it came; one
// with more than one key, and a key the view does not read, are handed on.
func TestTheMasterRunnersAreSentOnAndOtherAsksHandedOn(t *testing.T) {
	s := &Service{}
	resp, err := s.build(context.Background(), auth.Principal{}, door{Runner: true}, url.Values{"fy": {"2029"}})
	if err != nil || resp.Redirect != "/target-distribution?fy=2029" {
		t.Errorf("sent on: %v %v", resp, err)
	}
	if _, err := s.build(context.Background(), auth.Principal{}, door{Runner: true},
		url.Values{"fy": {"2029"}, "tab": {"all"}}); !errors.Is(err, errPassOn) {
		t.Errorf("a many-part ask: %v, want handed on", err)
	}
	if _, err := s.build(context.Background(), auth.Principal{}, door{Scoped: true},
		url.Values{"page": {"2"}}); !errors.Is(err, errPassOn) {
		t.Errorf("an unread key: %v, want handed on", err)
	}
}
