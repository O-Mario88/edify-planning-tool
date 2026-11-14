package ssaverify

import (
	"net/url"
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

func principal(active string, roles ...string) auth.Principal {
	return auth.Principal{Account: auth.Account{UserID: "u1", ActiveRole: active, Roles: roles}}
}

func TestRowWordsReadAsTheQueueWritesThem(t *testing.T) {
	names := map[string]string{"u2": "Grace A."}
	if got := collectorLabel(record{collector: "u2", kind: "ia"}, names); got != "Grace A. (Impact Assessment)" {
		t.Errorf("collector: %q", got)
	}
	if got := collectorLabel(record{uploader: "u9", kind: "field_team"}, names); got != "Field_Team" {
		t.Errorf("unknown kind: %q", got)
	}
	if sourceLabel(record{source: "staff_keyed", visitID: "a1"}) != "Keyed on a visit" || sourceLabel(record{source: "staff_keyed"}) != "Keyed by staff" ||
		sourceLabel(record{source: "odd"}) != "Recorded" {
		t.Error("source labels")
	}
	if floatText(6.8) != "6.8" || floatText(7) != "7.0" {
		t.Errorf("float: %q %q", floatText(6.8), floatText(7))
	}
	if w, tone := state(record{}, "returned", false, false, names); w != "Returned by a verifier: no reason recorded" || tone != "danger" {
		t.Errorf("returned: %q", w)
	}
	if w, _ := state(record{}, "pending", false, true, names); w != "Your scores: a different verifier confirms them" {
		t.Errorf("own: %q", w)
	}
}

func TestTheVisitDoorFollowsTheReader(t *testing.T) {
	partner := record{visitID: "a1", visitDelivery: "partner"}
	if visitURL(principal("ImpactAssessment"), partner) != "/ia/partner-evidence/a1/" ||
		visitURL(principal("CountryDirector"), record{visitID: "a1"}) != "/ia/verification/a1/" ||
		visitURL(principal("CCEO"), partner) != "/my-plan/a1" || visitURL(principal("CCEO"), record{}) != "" {
		t.Error("visit doors")
	}
}

func TestOnlyVerifiersDecideAndNeverTheirOwn(t *testing.T) {
	scope := schooldirectory.Scope{StaffID: "s1"}
	if decides(principal("CCEO", "CCEO"), scope, []string{"u1"}, &args{}) != "" {
		t.Error("a CCEO decides nothing")
	}
	if decides(principal("Program Lead", "CCEO"), scope, nil, &args{}) != "" {
		t.Error("an acting lead decides nothing")
	}
	a := &args{}
	if got := decides(principal("ImpactAssessment", "ImpactAssessment"), scope, []string{"u1", "s1"}, a); !strings.HasPrefix(got, "TRUE AND NOT") || len(*a) != 1 {
		t.Errorf("IA: %q %v", got, *a)
	}
	if got := decides(principal("Program Lead", "Program Lead"), scope, nil, &args{}); !strings.Contains(got, "IS DISTINCT FROM 'partner'") {
		t.Errorf("lead: %q", got)
	}
}

func TestAnEmptyQueueReadsItsMessageAndHint(t *testing.T) {
	r := page(principal("CountryDirector"), nil, "returned", false, nil, nil, nil, 1, 1, 0, url.Values{})
	tbl := r.Blocks[len(r.Blocks)-1].GetTable()
	if tbl.EmptyMessage != "No returned SSA records" || !strings.HasSuffix(tbl.Rows[0].Cells[0].Text, "re-keyed.") {
		t.Errorf("empty: %v", tbl)
	}
	if r.Blocks[0].GetPanel().Title != "Returned for correction" || r.Header.BackLabel != "Back to Quality Center" {
		t.Errorf("head: %v", r.Blocks[0])
	}
}
