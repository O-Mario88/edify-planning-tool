package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cpoHandover is coverage._Handover: the columns the kind is read from.
type cpoHandover struct {
	supportType, visitNumber, trainingNumber, projectID, expected, purpose string
}

// isDataCollection is rules.is_data_collection.
func isDataCollection(activityType, purpose string) bool {
	return slices.Contains(rules.DataCollectionTypes, activityType) || slices.Contains(rules.DataCollectionPurposes, purpose)
}

// packageKind is package_credit.assignment_kind for a hand-over at a Core
// school ("" for none). The dataset's hand-over names no training course, so
// the universal-training rule never applies here.
func packageKind(h cpoHandover, outside []string) string {
	c := rules.CountryOversight
	if h.projectID != "" && slices.Contains(outside, h.projectID) {
		return ""
	}
	if support := strings.ToLower(strings.TrimSpace(h.supportType)); support == "visit" || support == "training" {
		return support
	}
	if h.visitNumber != "" {
		return "visit"
	}
	if h.trainingNumber != "" {
		return "training"
	}
	if slices.Contains(c.NonPackageVisitPurposes, h.purpose) {
		return ""
	}
	expected := h.expected
	if expected == "" && h.purpose != "" {
		expected = c.PurposeActivityTypes[h.purpose]
	}
	if slices.Contains(c.PackageTrainingTypes, expected) || expected == "in_school_training" {
		return "training"
	}
	if slices.Contains(c.PackageVisitTypes, expected) {
		return "visit"
	}
	return ""
}

// handoverKind is coverage.handover_kind: "visit" or "training" for a Partner
// hand-over at a school of this type ("" for data collection, or none).
func handoverKind(schoolType string, h cpoHandover, outside []string) string {
	if isDataCollection(h.expected, h.purpose) {
		return ""
	}
	if schoolType == "core" {
		return packageKind(h, outside)
	}
	if slices.Contains(rules.CountryOversight.PackageTrainingTypes, h.expected) || h.expected == "in_school_training" {
		return "training"
	}
	return "visit"
}

// isSSAHandover is _is_ssa_handover: the rulebook's kind of the hand-over's
// expected visit (school_visit when none) is SSA Support.
func isSSAHandover(h cpoHandover) bool {
	expected := h.expected
	if expected == "" {
		expected = "school_visit"
	}
	return handoverVisitKind(expected, h.purpose) == rules.KindSSA
}

// handoverVisitKind is rules.visit_kind for a shape with no delivery named
// (a hand-over): SSA Support is not counted for it, so that kind is never
// returned... except that _is_ssa_handover asks for it with the default
// delivery, where visit_kind answers None for SSA. Kept as the rule reads.
func handoverVisitKind(activityType, purpose string) string {
	if !slices.Contains(rules.VisitShapeTypes, activityType) {
		return ""
	}
	if purpose == rules.CompanionPurpose || slices.Contains(rules.OutreachPurposes, purpose) {
		return ""
	}
	kind, ok := rules.PurposeKinds[purpose]
	if !ok {
		if slices.Contains(rules.DataCollectionPurposes, purpose) {
			kind = rules.KindSSA
		} else if k, ok := rules.TypeKinds[activityType]; ok {
			kind = k
		} else {
			kind = rules.KindSSA
		}
	}
	if kind == rules.KindSSA {
		return "" // not staff's: visit_kind answers None
	}
	return kind
}

// countHandovers is _load_handovers: the hand-overs not yet dated (assigned,
// read in every year from the one they were made in, from that year's first
// day in a later one) and those handed back (in the year they came back).
func countHandovers(ctx context.Context, db schooldirectory.Querier, byID map[string]*cpoSchool, ids []string, w cpoWindow, outside []string) error {
	c := rules.CountryOversight
	b := &sql{}
	q := `SELECT pa.school_id, COALESCE(pa.partner_id, ''), pa.status, pa.created_at, pa.returned_at, COALESCE(pa.support_type, ''),
  COALESCE(pa.visit_number, ''), COALESCE(pa.training_number, ''), COALESCE(pa.project_id, ''), COALESCE(pa.expected_activity_type, ''),
  COALESCE(pa.purpose_of_visit, '')
FROM partner_assignment pa WHERE pa.school_id = ANY(` + b.arg(ids) + `) AND pa.status = ANY(` +
		b.arg(append(slices.Clone(c.UnscheduledHandoverStatuses), c.ReturnedToStaff)) + `) AND ` + b.notOutside("pa.project_id", outside)
	rows, err := db.Query(ctx, q, b.args...)
	if err != nil {
		return fmt.Errorf("planningmonitor: the hand-overs: %w", err)
	}
	defer rows.Close()
	fy := 0
	fmt.Sscan(w.fy, &fy)
	local := func(t time.Time) time.Time {
		l := t.In(cpoLocation)
		return date(l.Year(), l.Month(), l.Day())
	}
	for rows.Next() {
		var id, partner, status string
		var created, returned *time.Time
		var h cpoHandover
		if err := rows.Scan(&id, &partner, &status, &created, &returned, &h.supportType, &h.visitNumber, &h.trainingNumber,
			&h.projectID, &h.expected, &h.purpose); err != nil {
			return err
		}
		s := byID[id]
		if s == nil || !s.governed() {
			continue
		}
		kind := handoverKind(s.schoolType, h, outside)
		isVisit := kind == "visit"
		if status == c.ReturnedToStaff {
			moment := returned
			if moment == nil {
				moment = created
			}
			if moment == nil || cpoOperationalFY(*moment) != fy {
				continue
			}
			if isVisit && w.bucket(local(*moment)) == 1 {
				s.partnerCounts(partner)[pReturned]++
			}
			continue
		}
		if created == nil || cpoOperationalFY(*created) > fy {
			continue
		}
		s.withPartner = true
		from := local(*created)
		if from.Before(w.fyStart) {
			from = w.fyStart
		}
		where := w.bucket(from)
		if kind == "training" {
			s.trainingWaiting[2]++
			if where < 2 {
				s.trainingWaiting[where]++
			}
		}
		if !isVisit {
			continue
		}
		p := s.partnerCounts(partner)
		p[pPendT]++
		if isSSAHandover(h) {
			p[pSSAT]++
		}
		switch where {
		case 0:
			p[pPendB]++
		case 1:
			p[pPendI]++
		}
	}
	return rows.Err()
}
