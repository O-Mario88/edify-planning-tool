package config

import (
	"fmt"
	"strconv"
	"strings"
)

// ClusterActions configures the Cluster Action Register's follow-up
// (owner brief, 2026-11-11, part 8: configurable deadlines, not hard-coded).
type ClusterActions struct {
	// RemindAfterDays: an unanswered request is reminded about after this
	// many days, and again after as many more.
	RemindAfterDays int
	// EscalateAfterDays: an action this many days past its target date is
	// escalated to the supervising Program Lead; 0 never escalates on its own.
	EscalateAfterDays int
	// InternalKey is sent with notices relayed into the existing
	// application's notifications (its EDIFY_INTERNAL_KEY); empty keeps
	// notices queued, undelivered, until it is set.
	InternalKey string
}

const (
	envClusterRemindDays   = "EDIFY_CLUSTER_ACTION_REMIND_DAYS"
	envClusterEscalateDays = "EDIFY_CLUSTER_ACTION_ESCALATE_DAYS"
	envInternalKey         = "EDIFY_INTERNAL_KEY"
	minInternalKeyLength   = 32
)

func loadClusterActions(getenv func(string) string) (ClusterActions, error) {
	out := ClusterActions{RemindAfterDays: 3, EscalateAfterDays: 14, InternalKey: strings.TrimSpace(getenv(envInternalKey))}
	for _, field := range []struct {
		name     string
		min, max int
		into     *int
	}{
		{envClusterRemindDays, 1, 30, &out.RemindAfterDays},
		{envClusterEscalateDays, 0, 90, &out.EscalateAfterDays},
	} {
		raw := strings.TrimSpace(getenv(field.name))
		if raw == "" {
			continue
		}
		days, err := strconv.Atoi(raw)
		if err != nil || days < field.min || days > field.max {
			return ClusterActions{}, fmt.Errorf("config: %s must be a whole number of days from %d to %d", field.name, field.min, field.max)
		}
		*field.into = days
	}
	if out.InternalKey != "" && len(out.InternalKey) < minInternalKeyLength {
		return ClusterActions{}, fmt.Errorf("config: %s must be at least %d characters", envInternalKey, minInternalKeyLength)
	}
	return out, nil
}
