// Package clusteroversight is the Cluster Oversight page as the app opens it
// (/cluster-oversight/), owned by Go (owner brief, 2026-11-11: "District and
// Cluster management"): the Command Center, every cluster the reader may see
// on one line, with the same sections, year filter, figures, links and pages
// as the existing page (apps.frontend.views.cluster_management_views,
// apps.clusters.workspace and the reads behind it, and
// templates/pages/oversight/cluster_oversight.html), as the app's feed reads
// it (apps.mobile_feed).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_cluster_oversight_rules`;
// apps/clusters/test_cluster_oversight_rules_export.py fails when the two
// differ.
package clusteroversight

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Doors is what a role may do on the page, by the page's own gates.
type Doors struct {
	// Page: require_page_permission("cluster_oversight").
	Page bool `json:"page"`
	// Directory: the Clusters door among the sections.
	Directory bool `json:"directory"`
	// Cluster: a figure's link to the cluster profile.
	Cluster bool `json:"cluster"`
	// Loans: the count of schools holding a loan opens the loans tab.
	Loans bool `json:"loans"`
}

// Section is one of the page's sections (workspace.SECTIONS).
type Section struct {
	Key         string `json:"key"`
	Label       string `json:"label"`
	Description string `json:"description"`
	URL         string `json:"url"`
}

// Column is [label, numeric].
type Column struct {
	Label   string
	Numeric bool
}

// UnmarshalJSON reads the exported pair.
func (c *Column) UnmarshalJSON(raw []byte) error {
	pair := []any{}
	if err := json.Unmarshal(raw, &pair); err != nil || len(pair) != 2 {
		return fmt.Errorf("a column is [label, numeric]: %s", raw)
	}
	c.Label, _ = pair[0].(string)
	c.Numeric, _ = pair[1].(bool)
	return nil
}

// Dimension is [key, label, default weight] of one part of a score.
type Dimension struct {
	Key, Label string
	Weight     float64
}

// UnmarshalJSON reads the exported triple.
func (d *Dimension) UnmarshalJSON(raw []byte) error {
	triple := []any{}
	if err := json.Unmarshal(raw, &triple); err != nil || len(triple) != 3 {
		return fmt.Errorf("a dimension is [key, label, weight]: %s", raw)
	}
	d.Key, _ = triple[0].(string)
	d.Label, _ = triple[1].(string)
	d.Weight, _ = triple[2].(float64)
	return nil
}

// Band is [floor, label, tone]; the last has no floor (no score).
type Band struct {
	Floor       *float64
	Label, Tone string
}

// UnmarshalJSON reads the exported triple.
func (b *Band) UnmarshalJSON(raw []byte) error {
	triple := []any{}
	if err := json.Unmarshal(raw, &triple); err != nil || len(triple) != 3 {
		return fmt.Errorf("a band is [floor, label, tone]: %s", raw)
	}
	if floor, ok := triple[0].(float64); ok {
		b.Floor = &floor
	}
	b.Label, _ = triple[1].(string)
	b.Tone, _ = triple[2].(string)
	return nil
}

// Level is [number, label] of a maturity level.
type Level struct {
	Number int
	Label  string
}

// UnmarshalJSON reads the exported pair.
func (l *Level) UnmarshalJSON(raw []byte) error {
	pair := []any{}
	if err := json.Unmarshal(raw, &pair); err != nil || len(pair) != 2 {
		return fmt.Errorf("a level is [number, label]: %s", raw)
	}
	number, _ := pair[0].(float64)
	l.Number = int(number)
	l.Label, _ = pair[1].(string)
	return nil
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors              map[string]Doors `json:"doors"`
	FeedOpensSections  bool             `json:"feed_opens_sections"`
	NotPassedQueryKeys []string         `json:"not_passed_query_keys"`
	TablePageSize      int              `json:"table_page_size"`
	Sections           []Section        `json:"sections"`
	DefaultSection     string           `json:"default_section"`
	Command            struct {
		Title   string   `json:"title"`
		Columns []Column `json:"columns"`
		Note    string   `json:"note"`
		Empty   string   `json:"empty"`
	} `json:"command"`
	Dash                   string      `json:"dash"`
	MissedInARowAlert      int         `json:"missed_in_a_row_alert"`
	OperatingStatuses      []string    `json:"operating_statuses"`
	ClusterSessionTypes    []string    `json:"cluster_session_types"`
	TrainingSessionTypes   []string    `json:"training_session_types"`
	TrainingTypes          []string    `json:"training_types"`
	LastActivityTypes      []string    `json:"last_activity_types"`
	DeliveredStatuses      []string    `json:"delivered_statuses"`
	NotInPlanStatuses      []string    `json:"not_in_plan_statuses"`
	ConfirmedStatus        string      `json:"confirmed_status"`
	CurrentSSAStatuses     []string    `json:"current_ssa_statuses"`
	FundedLoanStatuses     []string    `json:"funded_loan_statuses"`
	StoryDraftStatus       string      `json:"story_draft_status"`
	StoryApprovedStatus    string      `json:"story_approved_status"`
	PublishedMappingStatus string      `json:"published_mapping_status"`
	SSAInterventions       [][2]string `json:"ssa_interventions"`
	Change                 struct {
		MinIntervalDays   int     `json:"min_interval_days"`
		StrongScore       float64 `json:"strong_score"`
		Improved          string  `json:"improved"`
		Declined          string  `json:"declined"`
		NoChange          string  `json:"no_change"`
		MaintainedStrong  string  `json:"maintained_strong"`
		MaintainDirection string  `json:"maintain_direction"`
	} `json:"change"`
	Scores map[string]struct {
		Title      string      `json:"title"`
		Dimensions []Dimension `json:"dimensions"`
	} `json:"scores"`
	Bands            []Band             `json:"bands"`
	MaturityLevels   []Level            `json:"maturity_levels"`
	MaturityDefaults map[string]float64 `json:"maturity_defaults"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	err := json.Unmarshal(raw, &r)
	switch {
	case err != nil, len(r.Doors) == 0, len(r.Sections) == 0, len(r.Command.Columns) != columnCount,
		len(r.SSAInterventions) == 0, len(r.Scores) != 4, len(r.Bands) != 4, r.TablePageSize < 1,
		len(r.MaturityDefaults) == 0, r.Dash == "":
		panic(fmt.Sprintf("clusteroversight: the embedded rules are unreadable: %v", err))
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }

// interventionLabel is dict(SsaIntervention.choices).get(key), and the
// page's own wording of a key the choices do not hold
// (key.replace("_", " ").title()).
func interventionLabel(key string) string {
	for _, iv := range rules.SSAInterventions {
		if iv[0] == key {
			return iv[1]
		}
	}
	return pyTitle(replaceUnderscores(key))
}
