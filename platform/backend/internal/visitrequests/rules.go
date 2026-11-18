// Package visitrequests is the Visit Requests page in Go
// (visit_request_views.visit_requests_page over apps.planning.visit_requests,
// pages/planning/visit_requests.html, as the existing feed reads it): the
// visits other staff ask to make to the reader's schools, and the requests
// the reader filed with what became of them. Approving and declining are the
// existing application's.
package visitrequests

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// role is what one role is given on the page.
type role struct {
	Page         bool `json:"page"`
	Requester    bool `json:"requester"`
	OpenSchool   bool `json:"open_school"`
	OpenDistrict bool `json:"open_district"`
}

var rules = func() (r struct {
	Roles    map[string]role `json:"roles"`
	Awaiting string          `json:"awaiting"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("visitrequests: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || r.Awaiting == "" {
		panic("visitrequests: rules.json lacks the doors or the awaiting status")
	}
	return r
}()
