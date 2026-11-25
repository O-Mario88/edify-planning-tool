package iareports

import (
	"context"
	"net/url"
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

// Drawer draws a report drawer Go draws; served is false for any other path
// and for a reader the page gate refuses (refused as the page is).
func (r Reports) Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error) {
	path, query, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, PagePath) || !handled(path) {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, true, &Refusal{Message: pageRefusal, Page: true}
	}
	q, _ := url.ParseQuery(query)
	switch strings.TrimSuffix(path, "/") {
	case NewPath:
		d, err := r.newDrawer(ctx, p, q.Get("project"))
		return d, true, err
	}
	return nil, false, nil
}

// Save makes a report drawer's save; served is false for a drawer Go does
// not save.
func (r Reports) Save(ctx context.Context, p auth.Principal, rawPath string, values map[string]string) (Saved, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, PagePath) || !handled(path) {
		return Saved{}, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return Saved{}, true, &Refusal{Message: "This drawer is not available."}
	}
	switch strings.TrimSuffix(path, "/") {
	case NewPath:
		if !mayAuthor(p) {
			// The drawer has no form for anyone else.
			return Saved{}, true, &Refusal{Message: "This drawer cannot be saved here."}
		}
		saved, err := r.create(ctx, p, values)
		return saved, true, err
	}
	return Saved{}, false, nil
}

// handled says whether Go draws the drawer at path.
func handled(path string) bool {
	switch strings.TrimSuffix(path, "/") {
	case NewPath:
		return true
	}
	return false
}
