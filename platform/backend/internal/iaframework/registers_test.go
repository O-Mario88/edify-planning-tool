package iaframework

import (
	"context"
	"testing"
)

func ip(n int) *int { return &n }

func TestTheRuleWordsReadAsTheRegisterWritesThem(t *testing.T) {
	if got := slug("loan-purpose-" + "Class Room/Build"); got != "loan-purpose-class-room-build" {
		t.Errorf("slug: %q", got)
	}
	if window(&mapping{}) != "No window" || window(&mapping{min: ip(30), max: ip(180)}) != "30 / — / 180 days" {
		t.Errorf("window: %q", window(&mapping{min: ip(30), max: ip(180)}))
	}
	if ruleState(nil) != "Mapping required" || ruleState(&mapping{status: "draft", author: "seed"}) != rules.ReferenceDefaultLabel ||
		ruleState(&mapping{status: "draft", reviewNote: "fix"}) != "Returned" || ruleState(&mapping{status: "published", author: "seed"}) != "Published" {
		t.Error("rule state")
	}
	for want, m := range map[string]mapping{
		"Not measured by a score":            {reason: "admin", intervention: "leadership"},
		"Leadership":                         {intervention: "leadership"},
		"Planner selects":                    {mode: "any_ssa_intervention"},
		"Inherited from the source activity": {mode: "inherit_from_source_activity"},
		"—":                                  {mode: "fixed"},
	} {
		if got := interventionText(&m); got != want {
			t.Errorf("interventionText(%+v) = %q, want %q", m, got, want)
		}
	}
}

func TestOnlyASecondReaderInTheCountryMayReview(t *testing.T) {
	ctx := context.Background()
	ia := &resolver{r: reader{id: "u1", role: rules.IARole, country: "Uganda"}, officers: map[string][]string{}}
	if ok, _ := ia.may(ctx, "u1", "Uganda"); ok {
		t.Error("an author never reviews their own work")
	}
	if ok, _ := ia.may(ctx, "u2", "Kenya"); ok {
		t.Error("another country's work is not this reader's")
	}
	if ok, _ := ia.may(ctx, "u2", ""); !ok {
		t.Error("a second IA officer reviews")
	}
	cd := &resolver{r: reader{id: "c1", role: rules.CDRole, country: "Uganda"}, officers: map[string][]string{"Uganda": {"u2"}}}
	if ok, _ := cd.may(ctx, "u2", "Uganda"); !ok {
		t.Error("the director acknowledges where the author is the only officer")
	}
	cd.officers["Uganda"] = []string{"u2", "u3"}
	if ok, _ := cd.may(ctx, "u2", "Uganda"); ok {
		t.Error("the director does not review where a second officer can")
	}
}
