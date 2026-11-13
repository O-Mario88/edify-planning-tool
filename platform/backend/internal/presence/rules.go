// Package presence stamps a signed-in person's presence for the requests the
// Go gateway answers itself (docs/migration/65), exactly as the existing
// application's SlidingSessionMiddleware does for the requests it answers
// (apps.accounts.presence.touch_presence, _next_beat, credit_presence_time):
// when they were last seen, on which page, doing what, the sitting's start,
// and the time since the beat before it credited to that beat's part of the
// platform and task (presence_time) and to its sign-in (login_event).
//
// The beat is written by one narrow function, gateway_presence.beat
// (deploy/db/presence_roles.sql); the gateway holds no UPDATE of those
// tables of its own. Which requests are stamped, and the words a beat's slot
// is called, are computed here from the existing vocabularies, exported to
// rules.json by `manage.py export_presence_rules`
// (apps/accounts/test_presence_rules_export.py fails when they differ). The
// parts of the platform a page belongs to are the Staff Activity Log's own
// port of presence_labels.section_for.
package presence

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
)

//go:embed rules.json
var rulesJSON []byte

type ruleSet struct {
	UntrackedPrefixes     []string    `json:"untracked_prefixes"`
	ReadMethods           []string    `json:"read_methods"`
	ActionPatterns        [][2]string `json:"action_patterns"`
	IDSegment             string      `json:"id_segment"`
	OnlineWindowSeconds   int         `json:"online_window_seconds"`
	IdleSeconds           int         `json:"idle_seconds"`
	FinalBeatSeconds      int         `json:"final_beat_seconds"`
	ActionIntervalSeconds int         `json:"action_interval_seconds"`
	BackgroundHeader      string      `json:"background_header"`
	Lengths               struct {
		Page      int `json:"page"`
		Action    int `json:"action"`
		LoginID   int `json:"login_id"`
		Section   int `json:"section"`
		WorkingOn int `json:"working_on"`
	} `json:"lengths"`
	TimeZone string `json:"time_zone"`
}

type pattern struct {
	re    *regexp.Regexp
	label string
}

var (
	rules     ruleSet
	actions   []pattern
	idSegment *regexp.Regexp
)

func init() {
	if err := json.Unmarshal(rulesJSON, &rules); err != nil {
		panic(fmt.Sprintf("presence: reading rules.json: %v", err))
	}
	for _, pair := range rules.ActionPatterns {
		actions = append(actions, pattern{regexp.MustCompile(pair[0]), pair[1]})
	}
	idSegment = regexp.MustCompile(rules.IDSegment)
}

// BackgroundHeader is the header that marks a request nobody made (the
// activity script's X-Edify-Background: 1). The gateway sends it when it
// asks the existing application for a page an answer of Go's shows (a
// redraw), so that read is not taken for the person working: Go has
// stamped the request they made.
func BackgroundHeader() string { return rules.BackgroundHeader }
