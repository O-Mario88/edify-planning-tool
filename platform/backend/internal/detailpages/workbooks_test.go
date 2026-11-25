package detailpages

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// A workbook export Go makes answers with its file, its refusal, or "not
// here yet" when the reader's export is not Go's; the page's query reaches
// it without the target.
func TestAWorkbookExportAnswersWithItsFileOrItsRefusal(t *testing.T) {
	var asked url.Values
	answer := func(stem string, handled bool, err error) WorkbookExport {
		return func(_ context.Context, _ auth.Principal, q url.Values) (string, []workbook.Sheet, bool, error) {
			asked = q
			return stem, []workbook.Sheet{{Title: "Log", Headers: []string{"Staff"}}}, handled, err
		}
	}
	for _, c := range []struct {
		name   string
		export WorkbookExport
		status int
		header string
	}{
		{"the file", answer("staff-activity-20261126-20261126", true, nil), http.StatusOK, `attachment; filename="staff-activity-20261126-20261126.xlsx"`},
		{"no page", answer("", true, pagegate.ErrNotAvailable), http.StatusForbidden, ""},
		{"a refusal", answer("", true, workbook.Refusal("The Staff Activity Log is for Programme Leads and the Country Director.")), http.StatusForbidden, ""},
		{"a failure", answer("", true, errors.New("ERROR: permission denied for table activity")), http.StatusInternalServerError, ""},
		{"not Go's", answer("", false, nil), http.StatusServiceUnavailable, ""},
	} {
		t.Run(c.name, func(t *testing.T) {
			s := NewService(nil, time.Now).WithWorkbook("/staff-activity/export", c.export)
			mux := http.NewServeMux()
			s.RegisterHTTP(mux, fixedAuth{role: "CountryDirector"})
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/quick-export?target=%2Fstaff-activity%2Fexport%2F&period=week", nil))
			if rec.Code != c.status || rec.Header().Get("Content-Disposition") != c.header {
				t.Fatalf("status %d %q, want %d %q", rec.Code, rec.Header().Get("Content-Disposition"), c.status, c.header)
			}
			if strings.Contains(rec.Body.String(), "ERROR") {
				t.Fatalf("the reader is shown the failure: %q", rec.Body.String())
			}
			if asked.Get("period") != "week" || asked.Has("target") {
				t.Fatalf("the export was asked %v", asked)
			}
		})
	}
}
