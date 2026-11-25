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
var reportDrawerPath = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/(edit|recommendations/new)$`)

// handled says whether Go draws the drawer at path: which, and the report.
func handled(path string) (string, string, bool) {
	path = strings.TrimSuffix(path, "/")
	if path == NewPath {
		return "new", "", true
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
	default:
		d, err = r.recommendationDrawer(ctx, p, id)
	}
	return d, true, err
}

// Save makes a report drawer's save; served is false for a drawer Go does
// not save.
func (r Reports) Save(ctx context.Context, p auth.Principal, rawPath string, values map[string]string) (Saved, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
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
	default:
		saved, err = r.addRecommendation(ctx, p, id, values)
	}
	return saved, true, err
}
