package closurepages

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

//go:embed rules.json
var rulesJSON []byte

// role is what one role is given on the closure pages.
type role struct {
	Publishing      bool               `json:"publishing"`
	OpenSchool      bool               `json:"open_school"`
	PublishingStrip *decisionlog.Strip `json:"publishing_strip"`
	Completed       bool               `json:"completed"`
	CompletedStrip  *decisionlog.Strip `json:"completed_strip"`
	Queue           bool               `json:"queue"`
}

var rules = func() (r struct {
	Roles                  map[string]role `json:"roles"`
	PublishStatusRank      map[string]int  `json:"publish_status_rank"`
	PublishStatusOtherRank int             `json:"publish_status_other_rank"`
	// The Closure Readiness Workspace's (queue.go).
	Queue struct {
		NotStarted       []string `json:"not_started_statuses"`
		CalledOff        []string `json:"called_off_statuses"`
		NotExecuted      []string `json:"not_executed_statuses"`
		IAVerified       []string `json:"ia_verified_statuses"`
		ClearedAdvance   []string `json:"cleared_advance_statuses"`
		MovedAdvance     []string `json:"money_moved_advance_statuses"`
		NoSalesforceType []string `json:"no_salesforce_record_types"`
		Limit            int      `json:"limit"`
	} `json:"queue"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("closurepages: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.PublishStatusRank) == 0 {
		panic("closurepages: rules.json lacks the doors or the publishing ranks")
	}
	if r.Queue.Limit <= 0 || len(r.Queue.NotExecuted) == 0 || len(r.Queue.MovedAdvance) == 0 {
		panic("closurepages: rules.json lacks the closure queue's checks")
	}
	return r
}()
