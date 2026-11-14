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
	// ScheduleTrainingPair: the app's Schedule drawer saves 32's In-school
	// Training and its school visit through internal/activities
	// (docs/migration/32); everything else is forwarded as before.
	ScheduleTrainingPair bool
	// GroupReschedule and GroupCancel: the app's group Reschedule and group
	// Cancel drawers (the bar for ticked rows) change 33.1's groups through
	// internal/activities (docs/migration/33); any other group is forwarded
	// whole, as before.
	GroupReschedule bool
	GroupCancel     bool
	// ScheduleGroupTraining: a cluster's Group Training (docs/migration/38)
	// through internal/activities where Go takes it; everything else is
	// forwarded as before. Nothing in the app reaches it yet (38.1).
	ScheduleGroupTraining bool
	// ScheduleClusterMeeting: a cluster meeting (docs/migration/49) through
	// internal/activities where Go takes it; everything else is forwarded
	// as before. Nothing in the app reaches it yet (38.1).
	ScheduleClusterMeeting bool
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
	// SaveScheduleTrainingPair is the name EDIFY_GO_SAVES uses for the
	// In-school Training and its school visit.
	SaveScheduleTrainingPair = "schedule_training_pair"
	// SaveGroupReschedule is the name EDIFY_GO_SAVES uses for the group move.
	SaveGroupReschedule = "group_reschedule"
	// SaveGroupCancel is the name EDIFY_GO_SAVES uses for the group cancel.
	SaveGroupCancel = "group_cancel"
	// SaveScheduleGroupTraining is the name EDIFY_GO_SAVES uses for a
	// cluster's Group Training.
	SaveScheduleGroupTraining = "schedule_group_training"
	// SaveScheduleClusterMeeting is the name EDIFY_GO_SAVES uses for a
	// cluster meeting.
	SaveScheduleClusterMeeting = "schedule_cluster_meeting"
)

// knownGoSaves are the saves the switch can name.
var knownGoSaves = []string{SaveScheduleVisit, SaveRescheduleVisit, SaveCancelVisit, SaveEditVisit, SaveScheduleTrainingPair,
	SaveGroupReschedule, SaveGroupCancel, SaveScheduleGroupTraining, SaveScheduleClusterMeeting}

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
		out.ScheduleTrainingPair = out.ScheduleTrainingPair || name == SaveScheduleTrainingPair
		out.GroupReschedule = out.GroupReschedule || name == SaveGroupReschedule
		out.GroupCancel = out.GroupCancel || name == SaveGroupCancel
		out.ScheduleGroupTraining = out.ScheduleGroupTraining || name == SaveScheduleGroupTraining
		out.ScheduleClusterMeeting = out.ScheduleClusterMeeting || name == SaveScheduleClusterMeeting
	}
	if existingApp == "" || internalKey == "" {
		return GoSaves{}, fmt.Errorf("config: %s needs %s and %s: the save asks the existing application for the form and the pricing",
			envGoSaves, envExistingAppURL, envInternalKey)
	}
	return out, nil
}

// Names are the saves Go makes, as EDIFY_GO_SAVES names them, in order.
func (g GoSaves) Names() []string {
	out := []string{}
	for _, s := range []struct {
		on   bool
		name string
	}{
		{g.ScheduleVisit, SaveScheduleVisit}, {g.RescheduleVisit, SaveRescheduleVisit}, {g.CancelVisit, SaveCancelVisit},
		{g.EditVisit, SaveEditVisit}, {g.ScheduleTrainingPair, SaveScheduleTrainingPair}, {g.GroupReschedule, SaveGroupReschedule},
		{g.GroupCancel, SaveGroupCancel}, {g.ScheduleGroupTraining, SaveScheduleGroupTraining}, {g.ScheduleClusterMeeting, SaveScheduleClusterMeeting},
	} {
		if s.on {
			out = append(out, s.name)
		}
	}
	return out
}
