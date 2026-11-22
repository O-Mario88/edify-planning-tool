package oversightportfolio

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

type stubMapAuth struct {
	principal auth.Principal
	err       error
}

func (s stubMapAuth) Authenticate(_ context.Context, _ string) (auth.Principal, error) {
	return s.principal, s.err
}

func TestCanReadMapData(t *testing.T) {
	allowed := []string{
		"Admin",
		"CountryDirector",
		"ImpactAssessment",
		"RegionalProgramLead",
		"RegionalVicePresident",
		"Program Lead",
		"CCEO",
	}
	for _, role := range allowed {
		if !CanReadMapData(role) {
			t.Errorf("expected role %q to be allowed to read map data", role)
		}
	}

	denied := []string{
		"Accountant",
		"HumanResources",
		"ClusterLeader",
		"PartnerAdmin",
		"PartnerFieldOfficer",
		"MfiLoanOfficer",
		"MfiPartnerAdmin",
		"ProjectCoordinator",
		"BusinessTransformationOfficer",
		"",
	}
	for _, role := range denied {
		if CanReadMapData(role) {
			t.Errorf("expected role %q to be denied map data", role)
		}
	}
}

func TestRegisterMapHTTPAuthAndRBAC(t *testing.T) {
	cm := NewCountryMap(NewService(nil, nil))

	t.Run("unauthenticated returns 401", func(t *testing.T) {
		mux := http.NewServeMux()
		cm.RegisterMapHTTP(mux, stubMapAuth{err: errors.New("no token")})
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/api/v1/country-map/data", nil)
		mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("got %d, want 401", rec.Code)
		}
	})

	t.Run("disallowed role returns 403", func(t *testing.T) {
		mux := http.NewServeMux()
		cm.RegisterMapHTTP(mux, stubMapAuth{principal: auth.Principal{ActiveRole: "PartnerFieldOfficer"}})
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/api/v1/country-map/data", nil)
		mux.ServeHTTP(rec, req)
		if rec.Code != http.StatusForbidden {
			t.Fatalf("got %d, want 403", rec.Code)
		}
	})
}
