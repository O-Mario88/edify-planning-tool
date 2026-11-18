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
}

var rules = func() (r struct {
	Roles                  map[string]role `json:"roles"`
	PublishStatusRank      map[string]int  `json:"publish_status_rank"`
	PublishStatusOtherRank int             `json:"publish_status_other_rank"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("closurepages: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.PublishStatusRank) == 0 {
		panic("closurepages: rules.json lacks the doors or the publishing ranks")
	}
	return r
}()
