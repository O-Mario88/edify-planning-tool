package partneroversight

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// annotate is completion_columns.annotate over the page's items (by their
// activity): the Salesforce ID, the Evidence words, whether both halves are
// in, what a done status still lacks, and the day completed work was done.
// A Partner's work is complete only with its form uploaded, read through
// gateway_read.activity_evidence_kind (the gateway may not read
// evidence_record itself).
func annotate(ctx context.Context, db schooldirectory.Querier, items []*item, today time.Time) error {
	c := rules.Work.Completion
	asked := []string{}
	for _, it := range items {
		if it.act != nil && it.act.delivery == rules.PartnerDelivery {
			asked = append(asked, it.act.id)
		}
	}
	kinds := map[string]map[string]bool{}
	if len(asked) > 0 {
		rows, err := db.Query(ctx, `SELECT activity_id, kind FROM gateway_read.activity_evidence_kind WHERE activity_id = ANY($1)`, asked)
		if err != nil {
			return fmt.Errorf("partneroversight: reading the forms uploaded: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id, kind string
			if err := rows.Scan(&id, &kind); err != nil {
				return fmt.Errorf("partneroversight: reading the forms uploaded: %w", err)
			}
			if kinds[id] == nil {
				kinds[id] = map[string]bool{}
			}
			kinds[id][kind] = true
		}
		if err := rows.Err(); err != nil {
			return err
		}
	}
	for _, it := range items {
		a := it.act
		if a == nil {
			// A hand-over not yet scheduled reads EMPTY.
			it.salesforceID, it.evidenceLabel, it.salesforceOK, it.evidenceOK = "", "", false, false
			it.completionGap, it.isComplete, it.completedOn = gap(it.activityStatus, false, false), false, nil
			continue
		}
		it.salesforceID = strings.TrimSpace(a.salesforce)
		it.salesforceOK = it.salesforceID != ""
		it.evidenceOK = true
		if a.delivery == rules.PartnerDelivery {
			it.evidenceLabel = evidenceLabel(a.activityType, kinds[a.id])
			it.evidenceOK = kinds[a.id][expectedKind(a.activityType)]
		}
		done := in(c.OfficerCompleted, it.activityStatus)
		it.isComplete = done && it.salesforceOK && it.evidenceOK
		it.completionGap = gap(it.activityStatus, it.salesforceOK, it.evidenceOK)
		it.completedOn = nil
		if done {
			if a.actualDelivery != nil {
				d := dateOf(*a.actualDelivery)
				it.completedOn = &d
			} else {
				it.completedOn = localDay(a.executionStarted)
			}
		}
	}
	return nil
}

// gap is completion_columns.completion_gap.
func gap(status string, sf, evidence bool) string {
	c := rules.Work.Completion
	switch {
	case !in(c.OfficerCompleted, status), sf && evidence:
		return ""
	case !sf && !evidence:
		return c.MissingBoth
	case !sf:
		return c.MissingSF
	}
	return c.MissingEvidence
}

func expectedKind(activityType string) string {
	if in(rules.Work.Completion.AttendanceTypes, activityType) {
		return "attendance_form"
	}
	return "visit_form"
}

// evidenceLabel is completion_columns.evidence_label: the form's name once
// it is in, else the kinds uploaded, "" when nothing is.
func evidenceLabel(activityType string, kinds map[string]bool) string {
	if len(kinds) == 0 {
		return ""
	}
	if kinds[expectedKind(activityType)] {
		if expectedKind(activityType) == "attendance_form" {
			return "Attendance"
		}
		return "Visit Form"
	}
	names := []string{}
	keys := make([]string, 0, len(kinds))
	for k := range kinds {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if label, ok := rules.Work.Completion.EvidenceKindLabels[k]; ok {
			names = append(names, label)
		} else {
			s := strings.ReplaceAll(k, "_", " ")
			names = append(names, strings.ToUpper(s[:1])+strings.ToLower(s[1:]))
		}
	}
	return strings.Join(names, ", ")
}

// orderForMonitoring is order_for_monitoring: by school name, then work not
// complete first by its date (undated last among it) with complete work at
// the bottom, then hand-backs nobody has decided on first — each a stable
// sort, as Python's. Work submitted with its form whose only gap is the
// Salesforce ID reads Verification: the reviewer enters it.
func orderForMonitoring(items []*item) {
	c := rules.Work.Completion
	for _, it := range items {
		if it.completionGap == c.MissingSF && in(rules.Work.AwaitingIA, it.activityStatus) && it.evidenceOK {
			it.completionGap = ""
		}
	}
	sort.SliceStable(items, func(a, b int) bool { return items[a].schoolName < items[b].schoolName })
	sort.SliceStable(items, func(a, b int) bool {
		x, y := items[a], items[b]
		if x.isComplete != y.isComplete {
			return !x.isComplete
		}
		if (x.scheduledDate == nil) != (y.scheduledDate == nil) {
			return x.scheduledDate != nil
		}
		if x.scheduledDate == nil {
			return false
		}
		return x.scheduledDate.Before(*y.scheduledDate)
	})
	sort.SliceStable(items, func(a, b int) bool { return items[a].awaitsStaffDecision() && !items[b].awaitsStaffDecision() })
}
