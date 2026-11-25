package oversightfollowup

import (
	"net/url"
	"testing"
)

// Django reads the last value: a link whose last follow-up is blank shows no
// placeholder; any other value does.
func TestOpeningReadsTheLastFollowUp(t *testing.T) {
	for raw, want := range map[string]bool{
		"":                          false,
		"followup=":                 false,
		"followup=a&followup=":      false,
		"followup=&followup=b":      true,
		"followup=x&view=trainings": true,
	} {
		q, _ := url.ParseQuery(raw)
		if got := Opening(q) != nil; got != want {
			t.Errorf("%q: %v, want %v", raw, got, want)
		}
	}
	q, _ := url.ParseQuery("followup=x")
	if text := Opening(q).GetPanel().GetItems()[0].GetText(); text != "Opening the follow-up…" {
		t.Errorf("caption %q", text)
	}
}
