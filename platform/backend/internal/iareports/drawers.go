package iareports

import (
	"context"
	"net/url"
	"regexp"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// Saved is a save's answer: the web's confirmation, and the report it is
// about.
type Saved struct {
	Message, ReportID string
}

// reportDrawerPath is a report's own drawers: edit, and a new
// recommendation.
var reportDrawerPath = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/(edit|recommendations/new|review|release/schools)$`)

// releasePath is one release's drawer.
var releasePath = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/releases/([A-Za-z0-9]{1,30})$`)

// respondPath is a released report's recommendation drawer.
var respondPath = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/recommendations/([A-Za-z0-9]{1,30})$`)

// handled says whether Go draws the drawer at path: which, and the report
// (with a recommendation's id after a slash).
func handled(path string) (string, string, bool) {
	path = strings.TrimSuffix(path, "/")
	if path == NewPath {
		return "new", "", true
	}
	if m := releasePath.FindStringSubmatch(path); m != nil {
		return "release", m[1] + "/" + m[2], true
	}
	if m := respondPath.FindStringSubmatch(path); m != nil && m[2] != "new" {
		return "respond", m[1] + "/" + m[2], true
	}
	if m := reportDrawerPath.FindStringSubmatch(path); m != nil {
		return m[2], m[1], true
	}
	return "", "", false
}

// Drawer draws a report drawer Go draws; served is false for any other path.
func (r Reports) Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error) {
	path, query, _ := strings.Cut(rawPath, "?")
	which, id, ok := handled(path)
	if !ok {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, true, &Refusal{Message: pageRefusal, Page: true}
	}
	var d *screensv1.PageDrawer
	var err error
	switch which {
	case "new":
		q, _ := url.ParseQuery(query)
		d, err = r.newDrawer(ctx, p, q.Get("project"))
	case "edit":
		d, err = r.editDrawer(ctx, p, id)
	case "review":
		d, err = r.reviewDrawer(ctx, p, id)
	case "release/schools":
		d, err = r.schoolsDrawer(ctx, p, id)
	case "respond":
		report, rec, _ := strings.Cut(id, "/")
		d, err = r.respondDrawer(ctx, p, report, rec)
	case "release":
		report, release, _ := strings.Cut(id, "/")
		var served bool
		if d, served, err = r.releaseDrawer(ctx, p, report, release); !served {
			return nil, false, nil
		}
	default:
		d, err = r.recommendationDrawer(ctx, p, id)
	}
	return d, true, err
}

// reportPagePath is a report's own page, whose one-button forms Submit for
// review and Withdraw post.
var reportPagePath = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/$`)

// pageForm is the page form a key names: its header button's key, or where
// the form posts.
func pageForm(id, form string) string {
	switch strings.TrimSuffix(form, "/") {
	case "submit_for_review", PagePath + id + "/submit":
		return "submit"
	case "withdraw", PagePath + id + "/withdraw":
		return "withdraw"
	case "start_a_correction", PagePath + id + "/correct":
		return "correct"
	case "release_to_country_leadership", PagePath + id + "/release/leadership":
		return "release"
	}
	return ""
}

// savePageForm is _save_page_form for a report's page: the form must be one
// the page draws for the reader.
func (r Reports) savePageForm(ctx context.Context, p auth.Principal, id, form string, values map[string]string) (Saved, error) {
	which := pageForm(id, form)
	x, err := r.visible(ctx, r.DB, p, id, false)
	if err != nil {
		return Saved{}, err
	}
	if x == nil {
		return Saved{}, refuse("This page is not available.")
	}
	author := x.author == p.UserID && p.ActiveRole == roleIA
	switch {
	case which == "submit" && author && x.status == statusDraft:
		return r.submit(ctx, p, id)
	case which == "withdraw" && author && (x.status == statusDraft || x.status == "submitted"):
		return r.withdraw(ctx, p, id, strings.TrimSpace(values["note"]))
	case which == "release" && x.status == "reviewed":
		return r.releaseToLeadership(ctx, p, id)
	case which == "correct" && p.ActiveRole == roleIA:
		// The page draws it for the country's officers on a correctable
		// report with no correction open; start_correction checks each.
		return r.correct(ctx, p, id)
	}
	return Saved{}, refuse("This form is not available.")
}

// Save makes a report drawer's save, or a report page's form; served is
// false for one Go does not save.
func (r Reports) Save(ctx context.Context, p auth.Principal, rawPath, form string, values map[string]string) (Saved, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	if m := briefPagePath.FindStringSubmatch(path); m != nil && form != "" {
		if strings.TrimSuffix(form, "/") != "/impact-briefs/"+m[1]+"/shared" {
			return Saved{}, false, nil
		}
		saved, err := r.saveBrief(ctx, p, m[1], values)
		return saved, true, err
	}
	if m := reportPagePath.FindStringSubmatch(path); m != nil && form != "" {
		if pageForm(m[1], form) == "" {
			return Saved{}, false, nil
		}
		if !pageaccess.CanOpen(p.ActiveRole, false, path) {
			return Saved{}, true, &Refusal{Message: "This page is not available."}
		}
		saved, err := r.savePageForm(ctx, p, m[1], form, values)
		return saved, true, err
	}
	which, id, ok := handled(path)
	if !ok {
		return Saved{}, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return Saved{}, true, &Refusal{Message: "This drawer is not available."}
	}
	// The feed saves the drawer it opens: one that is not there, or that has
	// no form for this reader, is not saved.
	d, served, err := r.Drawer(ctx, p, rawPath)
	switch {
	case !served:
		return Saved{}, false, nil
	case err != nil:
		if refused, ok := err.(*Refusal); ok && refused.NotFound {
			return Saved{}, true, &Refusal{Message: "This drawer is not available."}
		}
		return Saved{}, true, err
	case !d.GetCanSubmit():
		return Saved{}, true, &Refusal{Message: "This drawer cannot be saved here."}
	}
	var saved Saved
	switch which {
	case "new":
		saved, err = r.create(ctx, p, values)
	case "edit":
		saved, err = r.update(ctx, p, id, values)
	case "review":
		saved, err = r.review(ctx, p, id, values)
	case "release/schools":
		saved, err = r.releaseSchools(ctx, p, id, values)
	case "respond":
		report, rec, _ := strings.Cut(id, "/")
		saved, err = r.respond(ctx, p, report, rec, values)
	default:
		saved, err = r.addRecommendation(ctx, p, id, values)
	}
	return saved, true, err
}
