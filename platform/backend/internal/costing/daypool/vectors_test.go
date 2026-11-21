package daypool

import (
	_ "embed"
	"encoding/json"
	"reflect"
	"testing"
)

// vectors.json is the existing application's own answers
// (apps/budget/management/commands/export_costing_rules.py), asked of
// apps.daily_visit_batches.districts and .pricing over a grid of inputs.
//
//go:embed vectors.json
var vectorsJSON []byte

type vectorSet struct {
	ResolveDistrictType []struct {
		Role, Primary, Target *string
		Answer                string
	} `json:"resolve_district_type"`
	HQDistrictType []struct {
		District *string
		Answer   string
	} `json:"hq_district_type"`
	DayDistrictMark []struct {
		Types  []*string
		Answer string
	} `json:"day_district_mark"`
	DayKeys []struct {
		DistrictType     string  `json:"district_type"`
		AccommodationKey *string `json:"accommodation_key"`
		ReturnDay        bool    `json:"return_day"`
		Answer           []string
	} `json:"day_keys"`
	ComputeDailyPool []struct {
		Rates            map[string]int64
		DistrictType     string  `json:"district_type"`
		AccommodationKey *string `json:"accommodation_key"`
		ReturnDay        bool    `json:"return_day"`
		Pool             map[string]int64
		Refused          string
	} `json:"compute_daily_pool"`
	AllocatePool []struct {
		Pool   map[string]int64
		N      int
		Answer []map[string]int64
	} `json:"allocate_pool"`
	AccommodationKeyForUser []struct {
		Roles      []string
		ActiveRole *string `json:"active_role"`
		Answer     string
	} `json:"accommodation_key_for_user"`
	HoldsFieldRole []struct {
		Roles      []string
		ActiveRole *string `json:"active_role"`
		Answer     bool
	} `json:"holds_field_role"`
}

func loadVectors(t *testing.T) vectorSet {
	t.Helper()
	var v vectorSet
	if err := json.Unmarshal(vectorsJSON, &v); err != nil {
		t.Fatalf("vectors.json: %v", err)
	}
	return v
}

// text reads an absent value (None) as the existing code's _norm does: empty.
func text(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// A set the decoder missed (a renamed key, a wrong tag) would pass every
// test below by holding nothing.
func TestEveryVectorSetIsRead(t *testing.T) {
	v := loadVectors(t)
	for name, size := range map[string]int{
		"resolve_district_type":      len(v.ResolveDistrictType),
		"hq_district_type":           len(v.HQDistrictType),
		"day_district_mark":          len(v.DayDistrictMark),
		"day_keys":                   len(v.DayKeys),
		"compute_daily_pool":         len(v.ComputeDailyPool),
		"allocate_pool":              len(v.AllocatePool),
		"accommodation_key_for_user": len(v.AccommodationKeyForUser),
		"holds_field_role":           len(v.HoldsFieldRole),
	} {
		if size == 0 {
			t.Errorf("vectors.json: %s read no cases", name)
		}
	}
	refused, pooled := 0, 0
	for _, c := range v.ComputeDailyPool {
		if c.Refused != "" {
			refused++
		} else if len(c.Pool) > 0 {
			pooled++
		}
	}
	if refused == 0 || pooled == 0 {
		t.Errorf("compute_daily_pool: %d refused and %d priced; both kinds are needed", refused, pooled)
	}
}

func TestTheDistrictTypeIsResolvedAsTheExistingApplicationResolvesIt(t *testing.T) {
	v := loadVectors(t)
	for _, c := range v.ResolveDistrictType {
		got, err := ResolveDistrictType(text(c.Role), text(c.Primary), text(c.Target))
		if err != nil {
			got = "error"
		}
		if got != c.Answer {
			t.Errorf("ResolveDistrictType(%q, %q, %q) = %q, the existing application says %q",
				text(c.Role), text(c.Primary), text(c.Target), got, c.Answer)
		}
	}
	for _, c := range v.HQDistrictType {
		if got := HQDistrictType(text(c.District)); got != c.Answer {
			t.Errorf("HQDistrictType(%q) = %q, want %q", text(c.District), got, c.Answer)
		}
	}
}

func TestTheDayIsMarkedAsTheExistingApplicationMarksIt(t *testing.T) {
	for _, c := range loadVectors(t).DayDistrictMark {
		types := make([]string, len(c.Types))
		for i, ty := range c.Types {
			types[i] = text(ty)
		}
		if got := DayDistrictMark(types); got != c.Answer {
			t.Errorf("DayDistrictMark(%q) = %q, want %q", types, got, c.Answer)
		}
	}
}

func TestADayFetchesTheRatesTheExistingApplicationFetches(t *testing.T) {
	v := loadVectors(t)
	for _, c := range v.DayKeys {
		got := DayKeys(c.DistrictType, text(c.AccommodationKey), c.ReturnDay)
		if !reflect.DeepEqual(got, c.Answer) {
			t.Errorf("DayKeys(%q, %q, %v) = %q, want %q",
				c.DistrictType, text(c.AccommodationKey), c.ReturnDay, got, c.Answer)
		}
	}
	for _, c := range v.ComputeDailyPool {
		pool, err := ComputeDailyPool(c.Rates, c.DistrictType, text(c.AccommodationKey), c.ReturnDay)
		switch {
		case c.Refused != "":
			if err == nil || err.Error() != c.Refused {
				t.Errorf("ComputeDailyPool(%v, %q, %q, %v) refused with %v, want %q",
					c.Rates, c.DistrictType, text(c.AccommodationKey), c.ReturnDay, err, c.Refused)
			}
		case err != nil:
			t.Errorf("ComputeDailyPool(%v, %q, %q, %v): %v, want %v",
				c.Rates, c.DistrictType, text(c.AccommodationKey), c.ReturnDay, err, c.Pool)
		case !reflect.DeepEqual(pool.Amounts(), c.Pool):
			t.Errorf("ComputeDailyPool(%v, %q, %q, %v) = %v, want %v",
				c.Rates, c.DistrictType, text(c.AccommodationKey), c.ReturnDay, pool.Amounts(), c.Pool)
		}
	}
}

func TestThePoolIsSharedToTheShillingAsTheExistingApplicationSharesIt(t *testing.T) {
	for _, c := range loadVectors(t).AllocatePool {
		pool := make(Pool, 0, len(c.Pool))
		for key, amount := range c.Pool {
			pool = append(pool, Rate{Key: key, Amount: amount})
		}
		got := AllocatePool(pool, c.N)
		if len(got) == 0 && len(c.Answer) == 0 {
			continue
		}
		if !reflect.DeepEqual(got, c.Answer) {
			t.Errorf("AllocatePool(%v, %d) = %v, want %v", c.Pool, c.N, got, c.Answer)
		}
	}
}

func TestTheNightIsPaidAtTheRateTheExistingApplicationPays(t *testing.T) {
	v := loadVectors(t)
	for _, c := range v.AccommodationKeyForUser {
		if got := AccommodationKeyForUser(c.Roles, text(c.ActiveRole)); got != c.Answer {
			t.Errorf("AccommodationKeyForUser(%q, %q) = %q, want %q", c.Roles, text(c.ActiveRole), got, c.Answer)
		}
	}
	for _, c := range v.HoldsFieldRole {
		if got := HoldsFieldRole(c.Roles, text(c.ActiveRole)); got != c.Answer {
			t.Errorf("HoldsFieldRole(%q, %q) = %v, want %v", c.Roles, text(c.ActiveRole), got, c.Answer)
		}
	}
}
