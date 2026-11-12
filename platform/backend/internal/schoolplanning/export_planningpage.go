package schoolplanning

import (
	"fmt"
	"slices"
)

// What the Planning page's support filters (planning_support.filter_queryset,
// internal/planningpage) read: the badges' classification as conditions on
// the schools aliased s, so a filter and the badges on the rows it returns
// cannot disagree.

// Buckets are the badges' status buckets, by name: "planned",
// "awaiting_verification", "verified", "needs_replanning", and "counted"
// (all four).
func Buckets(name string) []string {
	switch name {
	case bucketPlanned:
		return rules.PlannedStatuses
	case bucketAwaiting:
		return rules.AwaitingVerificationStatuses
	case bucketVerified:
		return rules.VerifiedStatuses
	case bucketReplan:
		return rules.NeedsReplanningStatuses
	}
	return slices.Concat(rules.PlannedStatuses, rules.AwaitingVerificationStatuses, rules.VerifiedStatuses, rules.NeedsReplanningStatuses)
}

// VisitTypes are the activity types a visit badge counts.
func VisitTypes() []string { return rules.VisitTypes }

// flagOf is a catalogue item, aliased ci, that counts as training.
const flagOf = "(COALESCE(%[1]s.counts_toward_client_training, false) OR COALESCE(%[1]s.is_training_course, false))"

// kindCondition is planning_support._kind_q over the activity aliased a and
// its catalogue item aliased ci; kind "" is any.
func kindCondition(kind, a, ci string, arg func(any) string) string {
	flag := fmt.Sprintf(flagOf, ci)
	typeIn := func(types []string) string { return fmt.Sprintf("%s.activity_type = ANY(%s)", a, arg(types)) }
	switch kind {
	case KindVisits:
		return typeIn(rules.VisitTypes)
	case KindTrainings:
		return fmt.Sprintf("(%s OR (%s AND NOT %s))", typeIn(rules.TrainingTypes), flag, typeIn(rules.VisitTypes))
	case KindClusterMeetings:
		return fmt.Sprintf("(%s AND NOT %s)", typeIn(rules.ClusterMeetingTypes), flag)
	}
	return fmt.Sprintf("(%s OR %s)", typeIn(slices.Concat(rules.VisitTypes, rules.TrainingTypes, rules.ClusterMeetingTypes)), flag)
}

// CountedCondition is planning_support._counted: a school with at least one
// activity of the year the badges count as kind ("" for any) in statuses,
// by the three routes the badges read.
func CountedCondition(kind string, statuses []string, fy string, arg func(any) string) string {
	direct := fmt.Sprintf(`EXISTS (SELECT 1 FROM activity a LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
  WHERE a.school_id = s.id AND a.fy = %s AND a.deleted_at IS NULL AND a.status = ANY(%s) AND %s)`,
		arg(fy), arg(statuses), kindCondition(kind, "a", "ci", arg))
	if kind == KindVisits {
		return direct
	}
	postDelivery := slices.Concat(rules.AwaitingVerificationStatuses, rules.VerifiedStatuses)
	register := fmt.Sprintf(`EXISTS (SELECT 1 FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
  LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
  WHERE c.school_id = s.id AND a.fy = %s AND a.deleted_at IS NULL AND a.activity_type = ANY(%s)
    AND a.status = ANY(%s) AND (c.invited OR c.attended)
    AND NOT (a.status = ANY(%s) AND NOT c.attended) AND %s)`,
		arg(fy), arg(rules.ClusterSessionTypes), arg(statuses), arg(postDelivery), kindCondition(kind, "a", "ci", arg))
	delivered := []string{}
	for _, s := range statuses {
		if slices.Contains(postDelivery, s) {
			delivered = append(delivered, s)
		}
	}
	if len(delivered) == 0 {
		return "(" + direct + " OR " + register + ")"
	}
	attended := fmt.Sprintf(`EXISTS (SELECT 1 FROM activity a LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
  WHERE a.fy = %s AND a.deleted_at IS NULL AND a.activity_type = ANY(%s) AND a.status = ANY(%s)
    AND cardinality(a.attended_school_ids) > 0 AND s.id = ANY(a.attended_school_ids) AND %s)`,
		arg(fy), arg(rules.ClusterSessionTypes), arg(delivered), kindCondition(kind, "a", "ci", arg))
	return "(" + direct + " OR " + register + " OR " + attended + ")"
}

// PartnerSupportCondition is the Exists of a live hand-over
// (active_assignment_q(fy)) on the school aliased s.
func PartnerSupportCondition(fy string, arg func(any) string) string {
	return fmt.Sprintf(`EXISTS (SELECT 1 FROM partner_assignment pa LEFT JOIN activity sa ON sa.id = pa.scheduled_activity_id
  WHERE pa.school_id = s.id AND pa.status IS DISTINCT FROM 'returned_to_staff'
    AND (pa.scheduled_activity_id IS NULL
      OR (sa.deleted_at IS NULL AND NOT COALESCE(sa.status = ANY(%s), false) AND sa.fy >= %s)))`,
		arg(rules.ClosedHandoverActivityStatuses), arg(fy))
}
