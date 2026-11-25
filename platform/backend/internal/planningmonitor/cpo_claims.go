package planningmonitor

import "sort"

// cpoClaims is coverage.Claims: the slots one school's plan fills, in the
// window and in the year.
type cpoClaims struct {
	visitSlots, staffExpected, partnerExpected, deficit, trainingSlots int
	staff, staffCore, staffClient, partnerAssigned, partnerScheduled   int
	staffVerified, partnerVerified, training, trainingVerified         int
	trainingStaffSlots, trainingPartnerSlots                           int
	trainingStaff, trainingPartner, trainingPartnerAssigned            int
	meetingCovered                                                     bool
	cumStaff, cumPartnerAssigned, cumPartnerScheduled, cumTraining     int
	cumMeetingCovered                                                  bool
	anyStaff, anyPartnerScheduled, anyPartnerAssigned, anyTraining     bool
	returned                                                           int
	byPartner                                                          map[string][4]int
	staffGap, partnerGap                                               int
	outside                                                            bool
}

func firstIn(before, inside int) int {
	if before == 0 && inside > 0 {
		return 1
	}
	return 0
}

func one(b bool) int {
	if b {
		return 1
	}
	return 0
}

// partnerTotals is _partner_totals: the Partners' counts summed (one Partner's
// when only is set), and the Partners kept.
func partnerTotals(s *cpoSchool, only *string) ([pWidth]int, []string) {
	var totals [pWidth]int
	kept := []string{}
	for _, pid := range s.partnerOrder {
		if only != nil && pid != *only {
			continue
		}
		kept = append(kept, pid)
		for i, v := range s.partners[pid] {
			totals[i] += v
		}
	}
	return totals, kept
}

// claimsFor is coverage.claims_for; channel is "", "staff" or "partner".
func claimsFor(s *cpoSchool, a cpoAllocation, w cpoWindow, channel string, only *string) cpoClaims {
	c := rules.CountryOversight
	req := c.slots(s.family)
	var cl cpoClaims
	if !s.governed() {
		return cl
	}
	staffCounts := s.staff
	if channel == "partner" {
		staffCounts = [4]int{}
	}
	var p [pWidth]int
	kept := []string{}
	if channel != "staff" {
		p, kept = partnerTotals(s, only)
	}
	staffExpected, partnerExpected := a.staff, a.partner
	if channel == "partner" {
		staffExpected = 0
	}
	if channel == "staff" {
		partnerExpected = 0
	}
	cl.visitSlots, cl.staffExpected, cl.partnerExpected = staffExpected+partnerExpected, staffExpected, partnerExpected
	if channel != "partner" {
		cl.deficit = a.deficit
	}
	sb, si, _, sv := staffCounts[0], staffCounts[1], staffCounts[2], staffCounts[3]
	cl.returned = p[pReturned]

	switch s.family {
	case c.CoreFamily:
		cl.anyStaff = si > 0
		cl.anyPartnerScheduled = p[pSchedI] > 0
		cl.anyPartnerAssigned = p[pSchedI]+p[pPendI] > 0
		cap := 0
		if channel != "staff" {
			cap = req.Partner
		}
		schedB := min(p[pSchedB], cap)
		cl.partnerScheduled = min(p[pSchedI], cap-schedB)
		assignedB := min(p[pSchedB]+p[pPendB], cap)
		cl.partnerAssigned = max(cl.partnerScheduled, min(p[pSchedI]+p[pPendI], cap-assignedB))
		staffSlots := 0
		if channel != "partner" {
			staffSlots = req.Staff
		}
		staffB := min(sb, staffSlots)
		cl.staff = min(si, staffSlots-staffB)
		cl.staffCore = cl.staff
		cl.cumStaff = staffB + cl.staff
		cl.cumPartnerScheduled = schedB + cl.partnerScheduled
		cl.cumPartnerAssigned = assignedB + cl.partnerAssigned
	case c.ClientFamily:
		cl.anyStaff = si > 0
		cl.anyPartnerScheduled = p[pSchedI] > 0
		cl.anyPartnerAssigned = p[pSchedI]+p[pPendI] > 0
		switch {
		case s.staff[2] > 0:
			if channel != "partner" {
				cl.staff = firstIn(sb, si)
				cl.cumStaff = one(sb+si > 0)
			}
		case (p[pSchedT] > 0 || p[pPendT] > 0) && channel != "staff":
			cl.partnerScheduled = firstIn(p[pSchedB], p[pSchedI])
			cl.partnerAssigned = max(cl.partnerScheduled, firstIn(p[pSchedB]+p[pPendB], p[pSchedI]+p[pPendI]))
			cl.cumPartnerScheduled = one(p[pSchedB]+p[pSchedI] > 0)
			cl.cumPartnerAssigned = one(p[pSchedB]+p[pSchedI]+p[pPendB]+p[pPendI] > 0)
		}
		cl.staffClient = cl.staff
		cl.visitSlots = min(cl.visitSlots, req.Flexible)
	default:
		cl.outside = true
	}
	cl.staffVerified = min(sv, cl.staff)
	cl.partnerVerified = min(p[pVerified], cl.partnerScheduled)

	n := need(s.schoolType)
	staffNeed, partnerNeed, eitherNeed := n.StaffTrainings, n.PartnerTrainings, n.EitherTrainings
	cl.trainingSlots = staffNeed + partnerNeed + eitherNeed
	tb, ti, tv := s.training[0], s.training[1], s.training[3]
	pb, pi, pv := s.trainingPartner[0], s.trainingPartner[1], s.trainingPartner[3]
	wb, wi := s.trainingWaiting[0], s.trainingWaiting[1]
	var before int
	if eitherNeed > 0 {
		if a.partner > 0 && a.staff == 0 {
			cl.trainingPartnerSlots = eitherNeed
		} else {
			cl.trainingStaffSlots = eitherNeed
		}
		before = min(tb+pb, eitherNeed)
		cl.training = min(ti+pi, eitherNeed-before)
		cl.trainingStaff = min(ti, cl.training)
		cl.trainingPartner = cl.training - cl.trainingStaff
		held := one(wi > 0 && before == 0 && cl.trainingStaff == 0)
		cl.trainingPartnerAssigned = max(cl.trainingPartner, held)
	} else {
		cl.trainingStaffSlots, cl.trainingPartnerSlots = staffNeed, partnerNeed
		staffBefore, partnerBefore := min(tb, staffNeed), min(pb, partnerNeed)
		before = staffBefore + partnerBefore
		cl.trainingStaff = min(ti, staffNeed-staffBefore)
		cl.trainingPartner = min(pi, partnerNeed-partnerBefore)
		cl.training = cl.trainingStaff + cl.trainingPartner
		heldBefore := min(pb+wb, partnerNeed)
		cl.trainingPartnerAssigned = max(cl.trainingPartner, min(pi+wi, partnerNeed-heldBefore))
	}
	cl.cumTraining = before + cl.training
	cl.trainingVerified = min(tv+pv, cl.training)
	cl.anyTraining = cl.trainingSlots > 0 && ti+pi > 0
	cl.meetingCovered = s.meeting[1] > 0
	cl.cumMeetingCovered = s.meeting[0]+s.meeting[1] > 0

	staffOnStaff := min(cl.cumStaff, staffExpected)
	partnerOnPartner := min(cl.cumPartnerAssigned, partnerExpected)
	partnerOnStaff := cl.cumPartnerAssigned - partnerOnPartner
	staffOnPartner := cl.cumStaff - staffOnStaff
	cl.staffGap = max(0, staffExpected-staffOnStaff-partnerOnStaff)
	cl.partnerGap = max(0, partnerExpected-partnerOnPartner-staffOnPartner)

	if len(kept) > 0 {
		cl.byPartner = splitBetweenPartners(s, kept, cl.partnerAssigned, cl.partnerScheduled)
	}
	return cl
}

// splitBetweenPartners is _split_between_partners: a school's Partner claims
// shared between the Partners holding it, the most-dated first.
func splitBetweenPartners(s *cpoSchool, kept []string, assigned, scheduled int) map[string][4]int {
	order := append([]string{}, kept...)
	sort.SliceStable(order, func(i, j int) bool {
		a, b := s.partners[order[i]], s.partners[order[j]]
		if a[pSchedI] != b[pSchedI] {
			return a[pSchedI] > b[pSchedI]
		}
		if a[pSchedI]+a[pPendI] != b[pSchedI]+b[pPendI] {
			return a[pSchedI]+a[pPendI] > b[pSchedI]+b[pPendI]
		}
		return order[i] < order[j]
	})
	leftAssigned, leftScheduled := assigned, scheduled
	shares := map[string][4]int{}
	for _, pid := range order {
		counts := s.partners[pid]
		takeAssigned := min(counts[pSchedI]+counts[pPendI], leftAssigned)
		takeScheduled := min(counts[pSchedI], leftScheduled, takeAssigned)
		leftAssigned -= takeAssigned
		leftScheduled -= takeScheduled
		shares[pid] = [4]int{takeAssigned, takeScheduled, min(counts[pVerified], takeScheduled), counts[pReturned]}
	}
	return shares
}
