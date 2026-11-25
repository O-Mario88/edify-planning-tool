package detailpages

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// The service has no database in these tests: a page that reached for one
// before checking its reader would panic, so a pass proves the refusal came first.

var unscopedPages = []string{
	"/projects/analytics",
	"/projects/project-1",
	"/partners/partner-1",
	"/activities/activity-1",
	"/my-plan/activity-1",
	"/documents/staff-handbook",
	"/accounts/monthly-request",
}

func TestPagesWithoutRecordScopeAreHandedOnForEveryoneButAdmin(t *testing.T) {
	s := NewService(nil, time.Now)
	for _, role := range []string{"MfiLoanOfficer", "PartnerFieldOfficer", "CCEO", "Program Lead", "CountryDirector", "Accountant"} {
		for _, path := range unscopedPages {
			t.Run(role+" "+path, func(t *testing.T) {
				_, served, err := s.Build(context.Background(), auth.Principal{UserID: "u1", ActiveRole: role}, path, url.Values{})
				if !served || !errors.Is(err, pagegate.ErrNotAvailable) {
					t.Fatalf("served=%v err=%v, want it handed on", served, err)
				}
			})
		}
	}
}

// Country Planning Oversight's Project Schools table is not this package's:
// planningoversight answers every consolidated table.
func TestCountryOversightProjectSchoolsIsNotThisPackages(t *testing.T) {
	s := NewService(nil, time.Now)
	for _, role := range []string{"Admin", "CountryDirector", "CCEO"} {
		_, served, err := s.Build(context.Background(), auth.Principal{UserID: "u1", ActiveRole: role},
			"/country-planning-oversight/table/projects", url.Values{})
		if served || err != nil {
			t.Fatalf("%s: served=%v err=%v, want another package's", role, served, err)
		}
	}
}

func TestTheDjangoAbsentDashboardIsNotOpenToEveryRole(t *testing.T) {
	s := NewService(nil, time.Now)
	ctx := pagegate.WithDjangoAbsent(context.Background(), true)
	_, served, err := s.Build(ctx, auth.Principal{UserID: "u1", ActiveRole: "MfiLoanOfficer"}, "/dashboard", url.Values{})
	if !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Fatalf("served=%v err=%v, want it handed on", served, err)
	}
}

func TestFixedRoutesAreNotReadAsRecordIDs(t *testing.T) {
	s := NewService(nil, time.Now)
	admin := auth.Principal{UserID: "a1", ActiveRole: "Admin"}
	for _, path := range []string{
		"/projects/capacity/", "/projects/create", "/projects/filter", "/projects/filters-drawer",
		"/partners/create/", "/activities/closure/", "/my-plan/day-package", "/my-plan/export-drawer", "/my-plan/readiness/",
	} {
		t.Run(path, func(t *testing.T) {
			if _, served, err := s.Build(context.Background(), admin, path, url.Values{}); served || err != nil {
				t.Fatalf("served=%v err=%v, want it left to its own page", served, err)
			}
		})
	}
}

type fixedAuth struct{ role string }

func (a fixedAuth) Authenticate(context.Context, string) (auth.Principal, error) {
	return auth.Principal{UserID: "u1", ActiveRole: a.role}, nil
}
