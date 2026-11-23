package coreforms

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	modeFixed        = "fixed"
	modeMultiple     = "multiple_allowed"
	modeInherit      = "inherit_from_source_activity"
	modePrerequisite = "ssa_completion_prerequisite"
	catalogueAdmin   = "admin"
	followUpRank     = 20
	unrankedNeed     = 999
	recentDays       = 180
)

var (
	// activeSupportStatuses is ACTIVE_SUPPORT_STATUSES.
	activeSupportStatuses = []string{"planned", "scheduled", "assigned_to_partner", "partner_scheduled", "in_progress", "completion_started",
		"evidence_uploaded", "evidence_accepted", "salesforce_id_required", "submitted_to_pl", "awaiting_ia_verification"}
	// completedSupportStatuses is COMPLETED_SUPPORT_STATUSES.
	completedSupportStatuses = []string{"completed", "ia_verified", "accountant_confirmed", "closed"}
)

// rankedSSA is one ranked need with its band.
type rankedSSA struct {
	Need
	Band string
}

// catalogueItem is an effective Activity Catalogue item, as a recommendation
// reads it.
type catalogueItem struct {
	id, code, name, workflowKind, activityType              string
	standard, staff, individual, requiresCluster            bool
	clusterDelivery, nonSchool, conflict, deliveredRecently bool
}

// eligible is the recommendation's base query for a staff visit to one school.
func (i catalogueItem) eligible() bool { return i.staff && i.individual }

type itemMapping struct {
	intervention, mode string
	priority           int
}

// sourceActivity is the school's latest completed support that names an
// intervention: what a dynamic follow-up inherits.
type sourceActivity struct{ name, focus string }

// Suggestion is one catalogue response the drawer may open on.
type Suggestion struct {
	ID, WorkflowKind, Target, Reason string
	name, code                       string
	rank                             int
	conflict, recent                 bool
}

// BlockedGroup is the catalogue responses to the top need that cannot be
// delivered here, by the reason and route they share.
type BlockedGroup struct {
	Reason, Route string
	Names         []string
}

// UnmetNeed is the top need with no single-school response.
type UnmetNeed struct {
	Label             string
	StandardAvailable bool
	Groups            []BlockedGroup
}

// Recommendation is recommend_activities, as far as the drawer reads it.
type Recommendation struct {
	HasSSA   bool
	First    *Suggestion
	Priority rankedSSA
	Unmet    *UnmetNeed
	// All is every suggestion in rank order, primary answers first.
	All []Suggestion
}

type recommendInput struct {
	items     []catalogueItem
	mappings  map[string][]itemMapping
	ranked    []rankedSSA
	hasRecord bool
	source    *sourceActivity
}

// pyFloat is a Python float as a string: a whole number keeps its ".0".
func pyFloat(value float64) string {
	text := strconv.FormatFloat(value, 'f', -1, 64)
	if !strings.Contains(text, ".") {
		text += ".0"
	}
	return text
}

// titled is str.title() for an intervention's code.
func titled(code string) string {
	words := strings.Fields(strings.ReplaceAll(code, "_", " "))
	for i, word := range words {
		words[i] = strings.ToUpper(word[:1]) + strings.ToLower(word[1:])
	}
	return strings.Join(words, " ")
}

func hasMode(mappings []itemMapping, modes ...string) bool {
	return slices.ContainsFunc(mappings, func(m itemMapping) bool { return slices.Contains(modes, m.mode) })
}

// recommendFrom is recommend_activities for one school, staff delivery, no
// project and no cluster.
func recommendFrom(in recommendInput) Recommendation {
	if !in.hasRecord || len(in.ranked) == 0 {
		return noSSARecommendation(in)
	}
	rank := make(map[string]int, len(in.ranked))
	need := make(map[string]rankedSSA, len(in.ranked))
	for i, row := range in.ranked {
		rank[row.Code], need[row.Code] = i, row
	}
	var suggestions []Suggestion
	addressed := map[string]bool{}
	for _, item := range in.items {
		if !item.eligible() || item.requiresCluster {
			continue
		}
		mappings := in.mappings[item.id]
		if item.activityType != catalogueAdmin && answersARankedNeed(mappings, rank) {
			chosen := closestMapping(mappings, rank)
			row := need[chosen.intervention]
			addressed[chosen.intervention] = true
			suggestions = append(suggestions, suggestionOf(item, chosen.intervention,
				fmt.Sprintf("%s is %s at %s/10.", row.Label, row.Band, pyFloat(row.Score)), rank[chosen.intervention]))
		}
		if hasMode(mappings, modeInherit) {
			suggestions = append(suggestions, followUpSuggestion(item, in, rank))
		}
	}
	sort.SliceStable(suggestions, func(i, j int) bool { return suggestionBefore(suggestions[i], suggestions[j]) })
	out := Recommendation{HasSSA: true, Priority: in.ranked[0], All: suggestions}
	if len(suggestions) > 0 {
		out.First = &suggestions[0]
	}
	if !addressed[in.ranked[0].Code] {
		out.Unmet = unmetNeed(in)
	}
	return out
}

func noSSARecommendation(in recommendInput) Recommendation {
	var all []Suggestion
	for _, item := range in.items {
		if item.eligible() && hasMode(in.mappings[item.id], modePrerequisite) {
			all = append(all, suggestionOf(item, "", "No applicable verified SSA exists. Complete the SSA before intervention support is recommended.", 0))
		}
	}
	if len(all) == 0 {
		return Recommendation{}
	}
	return Recommendation{First: &all[0], All: all}
}

func answersARankedNeed(mappings []itemMapping, rank map[string]int) bool {
	return slices.ContainsFunc(mappings, func(m itemMapping) bool {
		_, ranked := rank[m.intervention]
		return ranked && (m.mode == modeFixed || m.mode == modeMultiple)
	})
}

// closestMapping is the active mapping to the most urgent need.
func closestMapping(mappings []itemMapping, rank map[string]int) itemMapping {
	var best *itemMapping
	for i := range mappings {
		m := &mappings[i]
		if _, ranked := rank[m.intervention]; !ranked {
			continue
		}
		if best == nil || mappingBefore(*m, *best, rank) {
			best = m
		}
	}
	return *best
}

func mappingBefore(a, b itemMapping, rank map[string]int) bool {
	if rank[a.intervention] != rank[b.intervention] {
		return rank[a.intervention] < rank[b.intervention]
	}
	if a.priority != b.priority {
		return a.priority < b.priority
	}
	return a.intervention < b.intervention
}

func suggestionOf(item catalogueItem, target, reason string, rank int) Suggestion {
	return Suggestion{ID: item.id, WorkflowKind: item.workflowKind, Target: target, Reason: reason, name: item.name, code: item.code,
		rank: rank, conflict: item.conflict, recent: item.deliveredRecently}
}

func followUpSuggestion(item catalogueItem, in recommendInput, rank map[string]int) Suggestion {
	if in.source != nil {
		position, ranked := rank[in.source.focus]
		if !ranked {
			position = unrankedNeed
		}
		reason := fmt.Sprintf("Follow up %s and inherit its %s intervention.", in.source.name, titled(in.source.focus))
		return suggestionOf(item, in.source.focus, reason, position+followUpRank)
	}
	top := in.ranked[0]
	reason := fmt.Sprintf("No completed source support is available. Address the current unresolved %s need at %s/10.", top.Label, pyFloat(top.Score))
	return suggestionOf(item, top.Code, reason, rank[top.Code]+followUpRank)
}

func suggestionBefore(a, b Suggestion) bool {
	if a.rank != b.rank {
		return a.rank < b.rank
	}
	if a.conflict != b.conflict {
		return b.conflict
	}
	if a.recent != b.recent {
		return b.recent
	}
	if x, y := strings.ToLower(a.name), strings.ToLower(b.name); x != y {
		return x < y
	}
	return a.code < b.code
}

// unmetNeed is what the drawer says of a top need no school-level work answers.
func unmetNeed(in recommendInput) *UnmetNeed {
	top := in.ranked[0]
	out := &UnmetNeed{Label: top.Label}
	grouped := map[[2]string][]string{}
	for _, item := range in.items {
		if item.eligible() && item.standard {
			out.StandardAvailable = true
		}
		if !slices.ContainsFunc(in.mappings[item.id], func(m itemMapping) bool { return m.intervention == top.Code }) {
			continue
		}
		key := [2]string{blockedReason(item), blockedRoute(item)}
		grouped[key] = append(grouped[key], item.name)
	}
	keys := make([][2]string, 0, len(grouped))
	for key := range grouped {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i][0] != keys[j][0] {
			return keys[i][0] < keys[j][0]
		}
		return keys[i][1] < keys[j][1]
	})
	for _, key := range keys {
		names := slices.Clone(grouped[key])
		sort.Strings(names)
		out.Groups = append(out.Groups, BlockedGroup{Reason: key[0], Route: key[1], Names: names})
	}
	return out
}

func blockedReason(item catalogueItem) string {
	var reasons []string
	if !item.individual {
		reasons = append(reasons, "not delivered to a single school")
	}
	if !item.staff {
		reasons = append(reasons, "not approved for staff delivery")
	}
	if len(reasons) == 0 {
		return "not eligible for this school right now"
	}
	return strings.Join(reasons, " and ")
}

func blockedRoute(item catalogueItem) string {
	switch {
	case item.nonSchool:
		return "schedule from the Work Plan page"
	case item.clusterDelivery:
		return "schedule through a cluster"
	}
	return "ask IA to review its catalogue delivery settings"
}

// readCatalogue is the effective catalogue on day, with what this school
// already has of each item.
func (s *Service) readCatalogue(ctx context.Context, schoolID, fy string, day, now time.Time) ([]catalogueItem, map[string][]itemMapping, error) {
	rows, err := s.db.Query(ctx, `
SELECT i.id, i.stable_code, i.display_name, COALESCE(i.workflow_kind, ''), COALESCE(i.activity_type, ''),
  i.standard_support, i.staff_delivery_allowed, i.individual_school_allowed, i.requires_cluster,
  i.cluster_delivery_allowed, i.non_school_allowed,
  EXISTS (SELECT 1 FROM activity a WHERE a.catalogue_item_id = i.id AND a.school_id = $2 AND a.fy = $3
    AND a.deleted_at IS NULL AND a.status = ANY($4)),
  EXISTS (SELECT 1 FROM activity a WHERE a.catalogue_item_id = i.id AND a.school_id = $2
    AND a.deleted_at IS NULL AND a.status = ANY($5) AND a.scheduled_date >= $6)
FROM activity_catalogue_item i
WHERE i.status = 'active' AND (i.effective_from IS NULL OR i.effective_from <= $1)
  AND (i.effective_to IS NULL OR i.effective_to >= $1)
ORDER BY i.display_name, i.id`, day.Format(time.DateOnly), schoolID, fy, activeSupportStatuses, completedSupportStatuses,
		now.AddDate(0, 0, -recentDays))
	if err != nil {
		return nil, nil, fmt.Errorf("coreforms: reading the catalogue: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (catalogueItem, error) {
		var i catalogueItem
		err := row.Scan(&i.id, &i.code, &i.name, &i.workflowKind, &i.activityType, &i.standard, &i.staff, &i.individual,
			&i.requiresCluster, &i.clusterDelivery, &i.nonSchool, &i.conflict, &i.deliveredRecently)
		return i, err
	})
	if err != nil {
		return nil, nil, fmt.Errorf("coreforms: reading a catalogue item: %w", err)
	}
	mapped, err := s.db.Query(ctx, `SELECT catalogue_item_id, COALESCE(intervention, ''), mapping_mode, priority
FROM activity_intervention_mapping WHERE active ORDER BY priority, id`)
	if err != nil {
		return nil, nil, fmt.Errorf("coreforms: reading the mappings: %w", err)
	}
	defer mapped.Close()
	mappings := map[string][]itemMapping{}
	for mapped.Next() {
		var id string
		var m itemMapping
		if err := mapped.Scan(&id, &m.intervention, &m.mode, &m.priority); err != nil {
			return nil, nil, fmt.Errorf("coreforms: reading a mapping: %w", err)
		}
		mappings[id] = append(mappings[id], m)
	}
	return items, mappings, mapped.Err()
}

// latestSource is the school's latest completed support naming an intervention.
func (s *Service) latestSource(ctx context.Context, schoolID string, typeLabels map[string]string) (*sourceActivity, error) {
	var name, kind, focus string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(activity_name_snapshot, ''), activity_type, focus_intervention FROM activity
WHERE school_id = $1 AND deleted_at IS NULL AND status = ANY($2)
  AND focus_intervention IS NOT NULL AND focus_intervention <> ''
ORDER BY planned_date DESC, created_at DESC LIMIT 1`, schoolID, completedSupportStatuses).Scan(&name, &kind, &focus)
	if err == pgx.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the latest completed support: %w", err)
	}
	if name == "" {
		name = typeLabels[kind]
	}
	return &sourceActivity{name: name, focus: focus}, nil
}
