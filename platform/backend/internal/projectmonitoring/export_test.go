package projectmonitoring

import (
	"context"
	"errors"
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// The Projects export answers only for a reader the Project Monitoring page
// is drawn for, and only the whole table: a role the page refuses, an
// acting appointment, a period, a status or a kind is handed on (the
// existing view answers those), before anything is read.
func TestTheProjectsExportIsHandedOnWhereThePageIsNotGos(t *testing.T) {
	s := NewService(nil, nil)
	for _, c := range []struct {
		name  string
		p     auth.Principal
		query url.Values
	}{
		{"a role the page refuses", auth.Principal{Account: auth.Account{ActiveRole: "Accountant"}}, nil},
		{"the Regional Vice President", auth.Principal{Account: auth.Account{ActiveRole: "RegionalVicePresident"}}, nil},
		{"an acting appointment", acting(), nil},
		{"a custom period", auth.Principal{Account: auth.Account{ActiveRole: "CountryDirector"}}, url.Values{"period": {"custom"}}},
		{"completed work", auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}, url.Values{"status": {"completed"}}},
		{"a school list", auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}, url.Values{"activity_type": {"visits"}}},
		{"partner schools", auth.Principal{Account: auth.Account{ActiveRole: "Admin"}}, url.Values{"project_status": {"partner"}}},
	} {
		if _, _, handled, err := s.Export(context.Background(), c.p, "", c.query); handled || err != nil {
			t.Errorf("%s: handled %v, %v", c.name, handled, err)
		}
	}
	// require_export_permission: a CCEO reads the page but may not export.
	cceo := auth.Principal{Account: auth.Account{ActiveRole: "CCEO"}}
	if _, _, handled, err := s.Export(context.Background(), cceo, "", nil); !handled || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("a CCEO: handled %v, %v", handled, err)
	}
}

// The file is named as filename_stem names it: one project by its code,
// spelt for a file name, or every project.
func TestTheProjectsExportIsNamedAsTheExistingOneIs(t *testing.T) {
	one := []projectRow{{p: project{ID: "p1", Code: "Kids & Co/2027"}}}
	if got := exportStem(one, "2027", true); got != "project-kids---co-2027-schools-FY2027" {
		t.Errorf("one project: %q", got)
	}
	if got := exportStem([]projectRow{{p: project{ID: "p2"}}}, "2027", true); got != "project-p2-schools-FY2027" {
		t.Errorf("no code: %q", got)
	}
	if got := exportStem(one, "2027", false); got != "special-projects-schools-FY2027" {
		t.Errorf("every project: %q", got)
	}
	if _, ok := ExportRoute(NewService(nil, nil))("/projects/p1/export"); !ok {
		t.Error("one project's export is not routed")
	}
	if _, ok := ExportRoute(NewService(nil, nil))("/projects/export"); !ok {
		t.Error("every project's export is not routed")
	}
	if _, ok := ExportRoute(NewService(nil, nil))("/projects/p1/edit"); ok {
		t.Error("a project's edit page is routed as its export")
	}
}

func acting() auth.Principal {
	p := auth.Principal{Account: auth.Account{ActiveRole: "CountryDirector"}}
	p.InActingAppointment = true
	return p
}
