package coverage

import (
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestCoverageRoundsAndTitlesAsThePageDoes(t *testing.T) {
	if pct(1, 8) != 12 || pct(3, 8) != 38 || pct(0, 0) != 0 || pct(7, 10) != 70 {
		t.Errorf("pct: %d %d %d %d", pct(1, 8), pct(3, 8), pct(0, 0), pct(7, 10))
	}
	if title("active") != "Active" || title("ON_HOLD") != "On_Hold" || title("") != "" {
		t.Errorf("title: %q %q", title("active"), title("ON_HOLD"))
	}
	if intcomma(1234567) != "1,234,567" {
		t.Error("intcomma")
	}
}

func TestAReaderWithNoSchoolsReadsTwoEmptyCards(t *testing.T) {
	r := page(auth.Principal{}, "2027", []string{"2027"}, 0, 0, nil, nil, url.Values{})
	if len(r.Blocks) != 4 {
		t.Fatalf("blocks: %v", r.Blocks)
	}
	if p := r.Blocks[2].GetPanel(); p.Title != "Reach by district · FY2027" || len(p.Items) != 2 {
		t.Errorf("district card: %v", p)
	}
	if p := r.Blocks[3].GetPanel(); p.Title != "Clusters" || p.Items[0].GetText() != "Clusters appear as schools are grouped for operations." {
		t.Errorf("cluster card: %v", p)
	}
	if m := r.Blocks[1].GetStrip().Metrics[3]; m.Value != "0%" || m.Note != "" {
		t.Errorf("rate: %v", m)
	}
}
