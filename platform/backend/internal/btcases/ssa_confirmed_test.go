package btcases

import (
	"testing"
	"time"
)

func TestWeaknessesAreScoresAtOrBelowTheirThreshold(t *testing.T) {
	cases := []struct {
		name   string
		scores map[string]string
		want   []string
	}{
		{"both weak, Financial Health first", map[string]string{governmentRequirement: "4.0", financialHealth: "5.5"},
			[]string{financialHealth, governmentRequirement}},
		{"just above the threshold is not weak", map[string]string{financialHealth: "5.500000000000001"}, nil},
		{"other interventions never count", map[string]string{"leadership": "1.0"}, nil},
		{"only government weak", map[string]string{financialHealth: "7.25", governmentRequirement: "2.333333333333333"},
			[]string{governmentRequirement}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := weaknesses(c.scores, "5.50", "5.50")
			if err != nil {
				t.Fatal(err)
			}
			if len(got) != len(c.want) {
				t.Fatalf("weaknesses = %+v, want %v", got, c.want)
			}
			for i, w := range got {
				if w.intervention != c.want[i] || w.threshold != "5.50" || w.score != c.scores[w.intervention] {
					t.Fatalf("weakness %d = %+v, want %s", i, w, c.want[i])
				}
			}
		})
	}
}

func TestWeaknessesRefuseAScoreThatIsNotANumber(t *testing.T) {
	if _, err := weaknesses(map[string]string{financialHealth: "nan?"}, "5.50", "5.50"); err == nil {
		t.Fatal("a score that is not a number was compared")
	}
}

func TestPyISOPrintsAsDjangoDoes(t *testing.T) {
	at := time.Date(2026, 11, 3, 9, 4, 5, 120000000, time.FixedZone("EAT", 3*3600))
	if got := pyISO(at); got != "2026-11-03T06:04:05.120000+00:00" {
		t.Fatalf("pyISO = %s", got)
	}
	if got := pyISO(at.Truncate(time.Second)); got != "2026-11-03T06:04:05+00:00" {
		t.Fatalf("pyISO whole second = %s", got)
	}
}

func TestFirstSetIsPythonOr(t *testing.T) {
	a, b, empty := "verifier", "uploader", ""
	if got := firstSet(&a, &b); *got != a {
		t.Fatalf("firstSet = %s", *got)
	}
	if got := firstSet(&empty, &b); *got != b {
		t.Fatalf("firstSet with an empty verifier = %s", *got)
	}
	if got := firstSet(nil, nil); got != nil {
		t.Fatalf("firstSet of nothing = %v", got)
	}
}
