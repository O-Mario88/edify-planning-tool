package config

import (
	"fmt"
	"slices"
	"strings"
)

// GoSaves names the saves Go makes instead of the existing application
// (docs/migration/27 §27.10). Every save is off unless EDIFY_GO_SAVES names
// it; the switch is refused outside development and staging, and a save it
// turns on still connects only through dbguard's checks.
type GoSaves struct {
	// ScheduleVisit: the app's Schedule drawer saves 27.3's visits through
	// internal/activities; everything else is forwarded as before.
	ScheduleVisit bool
	// RescheduleVisit: the app's Reschedule drawer moves 29.1's visits
	// through internal/activities (docs/migration/29); everything else is
	// forwarded as before.
	RescheduleVisit bool
	// CancelVisit: the app's Cancel drawer calls off 30.1's visits through
	// internal/activities (docs/migration/30); everything else is forwarded
	// as before.
	CancelVisit bool
	// EditVisit: the app's Edit drawer changes 31.1's visits' words through
	// internal/activities (docs/migration/31); everything else is forwarded
	// as before.
	EditVisit bool
}

const (
	envGoSaves = "EDIFY_GO_SAVES"
	// SaveScheduleVisit is the name EDIFY_GO_SAVES uses for the visit save.
	SaveScheduleVisit = "schedule_visit"
	// SaveRescheduleVisit is the name EDIFY_GO_SAVES uses for the move.
	SaveRescheduleVisit = "reschedule_visit"
	// SaveCancelVisit is the name EDIFY_GO_SAVES uses for the cancel.
	SaveCancelVisit = "cancel_visit"
	// SaveEditVisit is the name EDIFY_GO_SAVES uses for the edit.
	SaveEditVisit = "edit_visit"
)

// knownGoSaves are the saves the switch can name.
var knownGoSaves = []string{SaveScheduleVisit, SaveRescheduleVisit, SaveCancelVisit, SaveEditVisit}

// loadGoSaves reads EDIFY_GO_SAVES. A Go save asks the existing application
// for the drawer's form and for the pricing (money stays Django's until
// M12), so it needs that application's address and internal key.
func loadGoSaves(env Environment, getenv func(string) string, existingApp, internalKey string) (GoSaves, error) {
	names := splitList(getenv(envGoSaves))
	if len(names) == 0 {
		return GoSaves{}, nil
	}
	if env != Development && env != Staging {
		return GoSaves{}, fmt.Errorf("config: %s is refused in %s: Go saves run only in development or staging", envGoSaves, env)
	}
	var out GoSaves
	for _, name := range names {
		if !slices.Contains(knownGoSaves, name) {
			return GoSaves{}, fmt.Errorf("config: %s names %q; the saves Go can make are %s",
				envGoSaves, name, strings.Join(knownGoSaves, ", "))
		}
		out.ScheduleVisit = out.ScheduleVisit || name == SaveScheduleVisit
		out.RescheduleVisit = out.RescheduleVisit || name == SaveRescheduleVisit
		out.CancelVisit = out.CancelVisit || name == SaveCancelVisit
		out.EditVisit = out.EditVisit || name == SaveEditVisit
	}
	if existingApp == "" || internalKey == "" {
		return GoSaves{}, fmt.Errorf("config: %s needs %s and %s: the save asks the existing application for the form and the pricing",
			envGoSaves, envExistingAppURL, envInternalKey)
	}
	return out, nil
}
