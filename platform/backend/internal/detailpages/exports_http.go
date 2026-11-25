package detailpages

import (
	"context"
	"encoding/csv"
	"fmt"
	"net/http"
	"regexp"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// HTTPAuth validates Bearer tokens on HTTP endpoints.
type HTTPAuth interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// RegisterHTTP mounts authenticated real-PostgreSQL CSV export downloads for
// legacy /.../export and template links so none fall into a 404 or NotMovedYet.
func (s *Service) RegisterHTTP(mux *http.ServeMux, authn HTTPAuth) {
	mux.HandleFunc("GET /api/v1/quick-export", func(w http.ResponseWriter, r *http.Request) {
		p, err := authn.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		target := strings.TrimSuffix(strings.TrimSpace(r.URL.Query().Get("target")), "/")
		if s.serveWorkbook(w, r, p, target) || s.serveFile(w, r, p, target) {
			return
		}
		var name string
		var body []byte
		var fileErr error
		served := false
		if m := annexTarget.FindStringSubmatch(target); m != nil && s.annex != nil {
			name, body, fileErr = s.annex(r.Context(), p, m[1])
			served = true
		} else if m := releaseTarget.FindStringSubmatch(target); m != nil && s.releaseFile != nil {
			name, body, fileErr = s.releaseFile(r.Context(), p, m[1], m[2])
			served = true
		}
		if served {
			if fileErr != nil {
				http.Error(w, "This file is not available to you.", http.StatusNotFound)
				return
			}
			w.Header().Set("Content-Type", "text/csv; charset=utf-8")
			w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, name))
			w.Header().Set("Cache-Control", "no-store")
			_, _ = w.Write(body)
			return
		}
		switch {
		case target == "/schools/upload/template":
			s.writeSchoolUploadTemplate(w, p)
		default:
			http.Error(w, "Unknown export target", http.StatusNotFound)
		}
	})
}

// annexTarget is an impact report's evidence annex download.
var annexTarget = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/annex\.csv$`)

// releaseTarget is a released version's download.
var releaseTarget = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/releases/([A-Za-z0-9]{1,30})/download$`)

func startCSV(w http.ResponseWriter, filename string) *csv.Writer {
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	w.Header().Set("Cache-Control", "no-store")
	return csv.NewWriter(w)
}

// writeSchoolUploadTemplate is school_template_download_view: the upload's
// own column headings, required first, and its minimal sample row, for a
// role the School Upload page admits.
func (s *Service) writeSchoolUploadTemplate(w http.ResponseWriter, p auth.Principal) {
	if !pageaccess.CanOpen(p.ActiveRole, false, "/schools/upload/template") {
		http.Error(w, "You do not have access to this export.", http.StatusForbidden)
		return
	}
	w.Header().Set("Content-Type", "text/csv")
	w.Header().Set("Content-Disposition", `attachment; filename="school_upload_template.csv"`)
	cw := csv.NewWriter(w)
	cw.UseCRLF = true
	_ = cw.Write([]string{"School ID", "School Name", "District", "Sub County", "Current Partner Type", "Staff Name",
		"Enrolment", "Last Date of Enrolment", "Phone", "Primary Contact", "School Shipping Address"})
	_ = cw.Write([]string{"SCH-0001", "St. Mary's Primary School", "", "", "", "", "", "", "", "", ""})
	cw.Flush()
}
