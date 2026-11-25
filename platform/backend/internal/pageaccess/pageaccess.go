// Package pageaccess is apps.core.permissions.can_open_url: whether a role
// may open a link, by the page gate on the view the link resolves to. The
// existing URL patterns, in resolution order with each view's page gates and
// whether it is export-gated, are exported to routes.json; each role's answer
// for every page, and whether it holds the export permission, to pages.json.
// Unknown or ungated routes count as openable, as they do there.
package pageaccess

import (
	_ "embed"
	"encoding/json"
	"net/url"
	"regexp"
	"slices"
	"strings"
)

//go:embed routes.json
var routesJSON []byte

//go:embed pages.json
var pagesJSON []byte

type route struct {
	match  *regexp.Regexp
	pages  []string
	export bool
}

type roleAnswer struct {
	Pages  []string `json:"pages"`
	Export bool     `json:"export"`
}

var (
	routes         []route
	roles          map[string]roleAnswer
	memberWithheld []string
)

func init() {
	var raw []struct {
		Regex  string   `json:"regex"`
		Pages  []string `json:"pages"`
		Export bool     `json:"export"`
	}
	if err := json.Unmarshal(routesJSON, &raw); err != nil {
		panic("pageaccess: routes.json is unreadable: " + err.Error())
	}
	for _, r := range raw {
		// Python's \Z is RE2's \z: the very end of the path.
		routes = append(routes, route{match: regexp.MustCompile(strings.ReplaceAll(r.Regex, `\Z`, `\z`)), pages: r.Pages,
			export: r.Export})
	}
	var p struct {
		Roles          map[string]roleAnswer `json:"roles"`
		MemberWithheld []string              `json:"member_withheld"`
	}
	if err := json.Unmarshal(pagesJSON, &p); err != nil || len(p.Roles) == 0 {
		panic("pageaccess: pages.json is unreadable")
	}
	roles, memberWithheld = p.Roles, p.MemberWithheld
}

// resolve is resolve(path).func's gates: the first pattern the path (less
// its leading slash) matches.
func resolve(path string) (route, bool) {
	rest := strings.TrimPrefix(path, "/")
	for _, r := range routes {
		if r.match.MatchString(rest) {
			return r, true
		}
	}
	return route{}, false
}

// isExport is _is_export_request for an export-gated view.
func isExport(u *url.URL) bool {
	q := u.Query()
	if v := q["export"]; len(v) > 0 && slices.ContainsFunc(v, func(s string) bool { return s != "" }) {
		return true
	}
	if f := q["format"]; len(f) == 1 && f[0] == "csv" {
		return true
	}
	return strings.Contains(u.EscapedPath(), "export")
}

// CanOpen is can_open_url for an account working in activeRole;
// teamMember is a partner login that is a partner's team member
// (member_scope.is_team_member), whose withheld pages it may not open.
func CanOpen(activeRole string, teamMember bool, link string) bool {
	if link == "" {
		return false
	}
	u, err := url.Parse(link)
	// The existing resolver reads the path as written, still percent-encoded.
	path := u.EscapedPath()
	if err != nil || !strings.HasPrefix(path, "/") {
		return true // resolves to no view: nothing gates it
	}
	r, ok := resolve(path)
	if !ok {
		return true
	}
	answer := roles[activeRole]
	if r.export && isExport(u) && !answer.Export {
		return false
	}
	if len(r.pages) == 0 {
		return true
	}
	for _, page := range r.pages {
		if !slices.Contains(answer.Pages, page) {
			continue
		}
		if teamMember && slices.Contains(memberWithheld, page) {
			continue
		}
		return true
	}
	return false
}
