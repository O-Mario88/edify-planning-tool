package calendarpage

import "time"

// ActivityTypeLabel is Activity.get_activity_type_display: the type's label,
// or its value where the choices name none.
func ActivityTypeLabel(value string) string {
	if label, ok := typeLabels[value]; ok {
		return label
	}
	return value
}

// OfficerCompletedStatuses are the statuses completed work is in, which
// neither calendar draws (extended_views.off_calendar_done).
func OfficerCompletedStatuses() []string {
	return append([]string(nil), rules.OfficerCompletedStatuses...)
}

// Location is the platform's time zone, the one a calendar day is read in.
func Location() *time.Location { return location }
