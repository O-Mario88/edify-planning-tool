package clusterpage

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// What the Planning page (internal/planningpage) shares with a cluster's
// schools list: the Partner-supported school rule, the score groups, a
// badge cell's text and a fact's colour.

// SupportRuleOn is support_responsibility.visibility_enabled(reader).
func SupportRuleOn(p auth.Principal) bool { return supportRuleOn(p) }

// ScoreGroupItems are partials/ssa/score_group_columns.html's groups.
func ScoreGroupItems(groups []schooldirectory.SSAGroup) []*screensv1.PagePanelItem {
	return groupItems(groups)
}

// JoinedChips is a badge cell's text.
func JoinedChips(chips ...[]schoolplanning.Chip) string { return joinedChips(chips...) }

// FactTone is the feed's colour for a fact whose holder carries words.
func FactTone(classes string) string { return factTone(classes) }

// ScoreText is |floatformat:"-1".
func ScoreText(v float64) string { return scoreText(v) }
