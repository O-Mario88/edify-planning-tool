// Package helpcenter is the Knowledge Center's reading pages
// (apps.help_center.views, pages/help/*.html under layouts/help_center.html):
// the home, an article (and the role guide, workflow, feature and Getting
// Started addresses that open one), a category, troubleshooting, the
// glossary, release notes and search, each with the role-aware table of
// contents (services.knowledge_tree). Each page is written as its template
// writes it and read by the feed's own rules (feeddom).
//
// Handed on: whatever would write on a read (the home and an article when
// no article exists yet, so the canonical content is installed; the home
// when a published article is past its review date, which it marks, or no
// route has its article yet, which it maps), the contextual help (its route
// sync is timed by a cache Go cannot read), the print view, the exports, the
// Help manager's pages and every save; a reader the view's page permission
// refuses (the refusal is audited).
//
// The rules are exported to rules.json by `manage.py
// export_help_center_rules`; apps/help_center/test_help_center_rules_export.py
// fails when the two differ.
package helpcenter

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool   `json:"page"`
		View  bool   `json:"view"`
		Guide string `json:"guide"`
	} `json:"roles"`
	GuideRoles     map[string]string `json:"guide_roles"`
	Synonyms       map[string]string `json:"synonyms"`
	ReadableStates []string          `json:"readable_states"`
	Published      string            `json:"published"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.ReadableStates) == 0 || r.Published == "" {
		panic(fmt.Sprintf("helpcenter: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("helpcenter: " + err.Error())
	}
	return z
}()

// Service builds the pages.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// slugPart is Django's <slug:…> converter.
var slugPart = regexp.MustCompile(`^[-a-zA-Z0-9_]+$`)

// page is one address of the Knowledge Center: which page it is and the
// slug it names.
type page struct{ kind, slug string }

// prefixes are the addresses that name a slug, in help_center.urls.
var prefixes = [][2]string{
	{"/help/roles/", "role"}, {"/help/workflows/", "workflow"}, {"/help/features/", "feature"},
	{"/help/articles/", "article"}, {"/help/categories/", "category"},
}

// route is help_center.urls for the reading pages, or false for an address
// Go does not build.
func route(path string) (page, bool) {
	switch path {
	case "/help":
		return page{kind: "home"}, true
	case "/help/search", "/help/troubleshooting", "/help/glossary", "/help/release-notes":
		return page{kind: strings.TrimPrefix(path, "/help/")}, true
	case "/help/getting-started":
		return page{kind: "article", slug: "getting-started"}, true
	}
	for _, p := range prefixes {
		if rest, ok := strings.CutPrefix(path, p[0]); ok && slugPart.MatchString(rest) {
			return page{kind: p[1], slug: rest}, true
		}
	}
	return page{}, false
}

// Build answers a Knowledge Center reading page, or reports false for any
// other path or for a reading it hands on.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	at, ok := route(path)
	if !ok {
		return nil, false, nil
	}
	role := rules.Roles[p.ActiveRole]
	if !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !role.View {
		return nil, false, nil // refused by the view, which audits the refusal
	}
	r := &reader{s: s, ctx: ctx, p: p, role: p.ActiveRole, path: path}
	var (
		resp   *screensv1.GetPageResponse
		served bool
		err    error
	)
	switch at.kind {
	case "home":
		resp, served, err = r.home()
	case "article":
		resp, served, err = r.article(at.slug)
	case "role":
		resp, served, err = r.article(guideSlug(at.slug))
	case "workflow":
		resp, served, err = r.article("workflow-" + strings.TrimPrefix(at.slug, "workflow-"))
	case "feature":
		resp, served, err = r.article("feature-" + strings.TrimPrefix(at.slug, "feature-"))
	case "category":
		resp, served, err = r.category(at.slug)
	case "troubleshooting":
		resp, served, err = r.troubleshooting()
	case "glossary":
		resp, served, err = r.glossary(strings.TrimSpace(query.Get("q")))
	case "release-notes":
		resp, served, err = r.releaseNotes()
	case "search":
		resp, served, err = r.search(strings.TrimSpace(query.Get("q")))
	}
	if err != nil || !served {
		return nil, served, err
	}
	resp.WebPath = path
	return resp, true, nil
}

// guideSlug is slug_for_role(_role_from_slug(role_slug)): the guide of the
// role the address names, else of the address itself.
func guideSlug(roleSlug string) string {
	if role, ok := rules.GuideRoles[roleSlug]; ok {
		return rules.Roles[role].Guide
	}
	return "role-" + slugify(roleSlug)
}

var (
	notWord = regexp.MustCompile(`[^\w\s-]`)
	runs    = regexp.MustCompile(`[-\s]+`)
)

// slugify is django.utils.text.slugify for an address's slug (ASCII).
func slugify(s string) string {
	s = notWord.ReplaceAllString(strings.ToLower(s), "")
	return strings.Trim(runs.ReplaceAllString(s, "-"), "-_")
}

// day is the template's date:"j M Y" in the site's zone.
func day(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.In(zone).Format("2 Jan 2006")
}
