package fieldops

import (
	"errors"
	"testing"
)

func wholeSSA(score float64) []SSAScoreInput {
	out := make([]SSAScoreInput, 0, len(SSAInterventions))
	for _, iv := range SSAInterventions {
		out = append(out, SSAScoreInput{Intervention: iv.Key, Score: score})
	}
	return out
}

func TestAnSSAIsAllEightInterventionsOutOfTen(t *testing.T) {
	if err := checkSSAScores(wholeSSA(10)); err != nil {
		t.Fatalf("a whole SSA at 10: %v", err)
	}
	over := wholeSSA(5)
	over[3].Score = 10.1
	repeated := wholeSSA(5)
	repeated[7].Intervention = repeated[0].Intervention
	unknown := wholeSSA(5)
	unknown[0].Intervention = "school_leadership"
	for name, scores := range map[string][]SSAScoreInput{
		"two scores": wholeSSA(5)[:2], "none": nil, "above ten": over, "repeated": repeated, "unknown": unknown,
	} {
		if err := checkSSAScores(scores); !errors.Is(err, ErrInvalidInput) {
			t.Errorf("%s: %v, want invalid input", name, err)
		}
	}
}
