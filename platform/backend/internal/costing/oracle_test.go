package costing

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

type oracleActivity struct {
	ActivityType         string      `json:"activityType"`
	DeliveryType         string      `json:"deliveryType"`
	DistrictType         string      `json:"districtType"`
	AccommodationKey     *string     `json:"accommodationKey"`
	ReturnDay            bool        `json:"returnDay"`
	CostingKind          string      `json:"costingKind"`
	Facilitated          bool        `json:"facilitated"`
	ExpectedParticipants *int        `json:"expectedParticipants"`
	TeachersAttended     int         `json:"teachersAttended"`
	LeadersAttended      int         `json:"leadersAttended"`
	OtherParticipants    int         `json:"otherParticipants"`
	Nights               *int        `json:"nights"`
	Days                 int         `json:"days"`
	PrintingPages        int         `json:"printingPages"`
	PhotocopyPages       int         `json:"photocopyPages"`
	PhotocopyCopies      int         `json:"photocopyCopies"`
	LinkedRates          [][2]string `json:"linkedRates"`
}

func (o oracleActivity) activity() Activity {
	a := Activity{
		ActivityType: o.ActivityType, DeliveryType: o.DeliveryType, DistrictType: o.DistrictType,
		ReturnDay: o.ReturnDay, CostingKind: o.CostingKind, Facilitated: o.Facilitated,
		ExpectedParticipants: o.ExpectedParticipants, TeachersAttended: o.TeachersAttended,
		LeadersAttended: o.LeadersAttended, OtherParticipants: o.OtherParticipants,
		Nights: o.Nights, Days: o.Days, PrintingPages: o.PrintingPages,
		PhotocopyPages: o.PhotocopyPages, PhotocopyCopies: o.PhotocopyCopies, LinkedRates: o.LinkedRates,
	}
	if o.AccommodationKey != nil {
		a.AccommodationKey = *o.AccommodationKey
	}
	return a
}

type oracleLine struct {
	Label   string `json:"label"`
	Key     string `json:"key"`
	Unit    *int64 `json:"unit"`
	Qty     int64  `json:"qty"`
	Amount  int64  `json:"amount"`
	Missing bool   `json:"missing"`
}

type oracleCost struct {
	Amount       int64        `json:"amount"`
	CostMissing  bool         `json:"cost_missing"`
	MissingItems []string     `json:"missing_items"`
	Lines        []oracleLine `json:"lines"`
}

func asOracle(c Cost) oracleCost {
	o := oracleCost{Amount: c.Amount, CostMissing: c.CostMissing, MissingItems: c.MissingItems, Lines: []oracleLine{}}
	for _, l := range c.Lines {
		o.Lines = append(o.Lines, oracleLine(l))
	}
	return o
}

// TestGoPricesEveryOracleCaseAsTheExistingEngine compares Go's lines with
// those apps.budget.costing priced for the same activity on the same card
// (testdata/oracle.py writes the cases). Skipped unless
// EDIFY_COSTING_ORACLE names the file.
func TestGoPricesEveryOracleCaseAsTheExistingEngine(t *testing.T) {
	path := os.Getenv("EDIFY_COSTING_ORACLE")
	if path == "" {
		t.Skip("EDIFY_COSTING_ORACLE is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var oracle struct {
		Cards map[string]map[string]int64 `json:"cards"`
		Cases []struct {
			Card            string         `json:"card"`
			Activity        oracleActivity `json:"activity"`
			Cost            oracleCost     `json:"cost"`
			FacilitationFee oracleCost     `json:"facilitation_fee"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &oracle); err != nil {
		t.Fatal(err)
	}
	if len(oracle.Cases) == 0 {
		t.Fatal("the oracle holds no cases")
	}
	differing := 0
	for i, c := range oracle.Cases {
		card := oracle.Cards[c.Card]
		a := c.Activity.activity()
		for _, pair := range []struct {
			name      string
			got, want oracleCost
		}{
			{"cost", asOracle(CostForActivity(a, card)), c.Cost},
			{"facilitation fee", asOracle(FacilitationFeeCost(a, card)), c.FacilitationFee},
		} {
			if pair.want.Lines == nil {
				pair.want.Lines = []oracleLine{}
			}
			if pair.want.MissingItems == nil {
				pair.want.MissingItems = []string{}
			}
			if !reflect.DeepEqual(pair.got, pair.want) {
				differing++
				if differing <= 5 {
					g, _ := json.Marshal(pair.got)
					w, _ := json.Marshal(pair.want)
					in, _ := json.Marshal(c.Activity)
					t.Errorf("case %d (%s, card %s) %s\n in:   %s\n go:   %s\n want: %s", i, c.Activity.ActivityType, c.Card, pair.name, in, g, w)
				}
			}
		}
	}
	t.Logf("%d cases compared, %d differing", len(oracle.Cases), differing)
}
