package costing

import "fmt"

// Activity is what the recipe reads of an activity (the `a` dict of
// cost_for_activity). Counts arrive already as integers: a negative one
// counts as zero, as Python's _nonnegative_count has it.
type Activity struct {
	ActivityType     string
	DeliveryType     string // "partner" or anything else (staff)
	DistrictType     string // "secondary" or anything else (primary)
	AccommodationKey string // the traveller's night rate; unknown = the CCEO's
	ReturnDay        bool   // the last of a run of day visits
	CostingKind      string // core | onetest | tot | student_conference | proprietor_conference
	Facilitated      bool

	ExpectedParticipants *int // nil = no plan captured
	TeachersAttended     int
	LeadersAttended      int
	OtherParticipants    int

	Nights *int // nil = the default night
	Days   int  // 0 or less = one day

	PrintingPages   int
	PhotocopyPages  int
	PhotocopyCopies int

	// LinkedRates are the costs the Country Director added for the
	// activity's catalogue item, as (key, label), each one line.
	LinkedRates [][2]string
}

// Line is one cost line. Unit is nil when the card lacks the rate.
type Line struct {
	Label   string
	Key     string
	Unit    *int64
	Qty     int64
	Amount  int64
	Missing bool
}

// Cost is an activity's priced lines (ActivityCost).
type Cost struct {
	Amount       int64
	Lines        []Line
	CostMissing  bool
	MissingItems []string
}

func nonNegative(n int) int64 {
	if n < 0 {
		return 0
	}
	return int64(n)
}

func (a Activity) days() int64 {
	if a.Days < 1 {
		return 1
	}
	return int64(a.Days)
}

func (a Activity) participants(defaultN int64) int64 {
	if a.ExpectedParticipants != nil {
		return nonNegative(*a.ExpectedParticipants)
	}
	counted := nonNegative(a.TeachersAttended) + nonNegative(a.LeadersAttended) + nonNegative(a.OtherParticipants)
	if counted > 0 {
		return counted
	}
	return defaultN
}

// MaterialsQuantities is (pages to print, pages × copies to photocopy).
func MaterialsQuantities(a Activity) (int64, int64) {
	return nonNegative(a.PrintingPages), nonNegative(a.PhotocopyPages) * nonNegative(a.PhotocopyCopies)
}

// dayKeys is apps.daily_visit_batches.pricing.day_keys.
func dayKeys(profile, accommodationKey string, returnDay bool) []string {
	known := false
	for _, k := range rules.accommodationKeys {
		if k == accommodationKey {
			known = true
		}
	}
	if !known {
		accommodationKey = rules.accommodationKey
	}
	var keys []string
	for _, key := range rules.dayRequired[profile] {
		if key == rules.accommodationKey {
			key = accommodationKey
		}
		if returnDay && rules.returnDayDropped.has(key) {
			continue
		}
		keys = append(keys, key)
	}
	return keys
}

func isAccommodation(key string) bool {
	for _, k := range rules.accommodationKeys {
		if k == key {
			return true
		}
	}
	return false
}

type pricer struct {
	a     Activity
	rates map[string]int64
	lines []Line

	isPartner   bool
	isSecondary bool
}

func (p *pricer) add(label, key string, qty int64) {
	unit, ok := p.rates[key]
	line := Line{Label: label, Key: key, Qty: qty, Missing: !ok}
	if ok {
		u := unit
		line.Unit = &u
		line.Amount = unit * qty
	}
	p.lines = append(p.lines, line)
}

func (p *pricer) carries(key string) bool {
	_, ok := p.rates[key]
	return ok
}

// addRate is one of the owner's per-activity or materials rates, skipped on
// a card that does not carry it when the owner's list added it.
func (p *pricer) addRate(key string, qty int64) {
	if rules.optional.has(key) && !p.carries(key) {
		return
	}
	p.add(RateLabel(key), key, qty)
}

// addStaffVisitDay is the one recipe for a day away from base. nights < 0
// means the default (one a day, but the last).
func (p *pricer) addStaffVisitDay(days int64, nights int64) {
	profile := "primary"
	if p.isSecondary {
		profile = "secondary"
	}
	nightsAway := days
	if days > 1 {
		nightsAway = days - 1
	}
	if nights < 0 {
		nights = nightsAway
	}
	returnDay := days == 1 && p.a.ReturnDay
	optional := setOf(rules.dayOptional[profile])
	keys := append(dayKeys(profile, p.a.AccommodationKey, returnDay), rules.dayOptional[profile]...)
	for _, key := range keys {
		if optional.has(key) && !p.carries(key) {
			continue
		}
		var qty int64
		switch {
		case isAccommodation(key):
			qty = nights
		case key == rules.dinnerKey:
			qty = nightsAway
		default:
			qty = days
		}
		if qty <= 0 {
			continue
		}
		p.add(rules.dayLabels[key], key, qty)
	}
}

func (p *pricer) addStaffDay(days int64) {
	if p.isPartner {
		return
	}
	p.addStaffVisitDay(days, -1)
}

func (p *pricer) addMaterials() {
	printing, photocopying := MaterialsQuantities(p.a)
	if printing > 0 {
		p.addRate("printing_training_materials", printing)
	}
	if photocopying > 0 {
		p.addRate("photocopying_training_materials", photocopying)
	}
}

func (p *pricer) addMeals(key string, days int64) {
	if rules.optional.has(key) && !p.carries(key) {
		return
	}
	p.add(rules.rateLabels[key], key, p.a.participants(0)*days)
}

func (p *pricer) addFacilitationFee(days int64) {
	p.add(rules.rateLabels["group_training_facilitation_fee"], "group_training_facilitation_fee", days)
}

func (p *pricer) addVenue(days int64) {
	p.add(rules.rateLabels["group_training_venue_cost"], "group_training_venue_cost", days)
}

// travel: nil = the staff member travels and a partner does not.
func (p *pricer) addGroupSession(days int64, rateKey, mealsKey string, travel *bool) {
	if rateKey != "" {
		p.addRate(rateKey, 1)
	}
	if mealsKey != "" {
		p.addMeals(mealsKey, days)
	}
	p.addFacilitationFee(days)
	p.addVenue(days)
	p.addMaterials()
	switch {
	case travel == nil:
		p.addStaffDay(days)
	case *travel:
		p.addStaffVisitDay(days, -1)
	}
}

func (p *pricer) addMissionRate() {
	if p.a.CostingKind == "onetest" {
		p.addRate("onetest", 1)
	}
}

func (p *pricer) addPartnerRate(key, basis string) {
	p.add(fmt.Sprintf("%s [Rate basis: %s]", rules.rateLabels[key], basis), key, 1)
}

const (
	totMealsKey           = "tot_trainings_meals"
	clusterMealsKey       = "cluster_meetings_trainings_meals"
	groupTrainingMealsKey = "group_training_meals"
)

// CostForActivity prices an activity from the rate card
// (apps.budget.costing.cost_for_activity): the same lines, in the same
// order, with the same labels and amounts.
func CostForActivity(a Activity, card map[string]int64) Cost {
	p := &pricer{
		a:           a,
		rates:       WithRateAliases(card),
		isPartner:   a.DeliveryType == "partner",
		isSecondary: a.DistrictType == "secondary",
	}
	travel := true
	kind := a.CostingKind
	t := a.ActivityType
	inSchoolTraining := t == "in_school_training"
	isCore := kind == "core" || rules.coreWork.has(t)
	isSSA := rules.ssaWork.has(t)

	switch {
	case t == "field_event":
		p.addStaffVisitDay(a.days(), -1)
	case t == "programme_event":
		conference := ""
		if kind == "student_conference" || kind == "proprietor_conference" {
			conference = kind
		}
		p.addGroupSession(a.days(), conference, "", nil)
	case rules.clusterMeeting.has(t):
		days := a.days()
		p.addMeals(clusterMealsKey, days)
		p.addVenue(days)
		p.addMaterials()
		p.addStaffDay(days)
		if a.Facilitated {
			p.addFacilitationFee(days)
		}
	case rules.clusterTraining.has(t):
		p.addGroupSession(a.days(), "", groupTrainingMealsKey, &travel)
	case rules.training.has(t) && !inSchoolTraining:
		if kind == "tot" {
			p.addGroupSession(a.days(), "tot_trainings", totMealsKey, &travel)
		} else {
			p.addGroupSession(a.days(), "", groupTrainingMealsKey, &travel)
		}
	case p.isPartner:
		switch {
		case kind == "onetest":
			p.addPartnerRate("onetest", "per OneTest visit")
		case inSchoolTraining:
			p.addPartnerRate("client_partner_visit", "per school mission")
		case rules.visit.has(t) || isSSA:
			if isCore {
				p.addPartnerRate("core_partner_visit", "per activity")
			} else {
				p.addPartnerRate("client_partner_visit", "per activity")
			}
		default:
			p.addPartnerRate("partner_meetings", "per meeting")
		}
	case rules.visit.has(t) || inSchoolTraining:
		nights := int64(1)
		if a.Nights != nil {
			nights = nonNegative(*a.Nights)
		}
		p.addMissionRate()
		p.addStaffVisitDay(1, nights)
		if inSchoolTraining && a.Facilitated {
			p.addFacilitationFee(1)
		}
	case t == "partner_activity" || t == "project_activity":
		p.addPartnerRate("partner_meetings", "per meeting")
	default:
		p.addMissionRate()
		p.addStaffVisitDay(1, -1)
	}

	for _, kl := range a.LinkedRates {
		p.add(kl[1], kl[0], 1)
	}
	return summed(p.lines)
}

func summed(lines []Line) Cost {
	c := Cost{Lines: lines, MissingItems: []string{}}
	for _, l := range lines {
		c.Amount += l.Amount
		if l.Missing {
			c.CostMissing = true
			c.MissingItems = append(c.MissingItems, l.Key)
		}
	}
	for _, l := range lines {
		if l.Qty == 0 && rules.meals.has(l.Key) {
			c.MissingItems = append(c.MissingItems, "expectedParticipants")
			c.CostMissing = true
			break
		}
	}
	return c
}

// FacilitationFeeCost is the facilitation fee alone
// (apps.budget.costing.facilitation_fee_cost). Its missing item is the
// line's label, as there.
func FacilitationFeeCost(a Activity, card map[string]int64) Cost {
	const key = "group_training_facilitation_fee"
	p := &pricer{a: a, rates: WithRateAliases(card)}
	p.add(rules.rateLabels[key], key, a.days())
	line := p.lines[0]
	c := Cost{Amount: line.Amount, Lines: p.lines, CostMissing: line.Missing, MissingItems: []string{}}
	if line.Missing {
		c.MissingItems = []string{line.Label}
	}
	return c
}
