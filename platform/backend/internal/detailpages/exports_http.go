package detailpages

import (
	"context"
	"encoding/csv"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
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
		if organisationWideExport(target) && !(p.ActiveRole == rbac.Admin && rbac.Grants(p.ActiveRole, exportPermission)) {
			http.Error(w, "Your role cannot download this export.", http.StatusForbidden)
			return
		}
		fy := strings.TrimSpace(r.URL.Query().Get("fy"))
		if fy == "" {
			fy = schooldirectory.OperationalFY(s.now())
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
			s.writeSchoolUploadTemplate(w)
		case target == "/projects/export":
			s.exportProjectsCSV(r.Context(), w, fy, "")
		case strings.HasPrefix(target, "/projects/") && strings.HasSuffix(target, "/export"):
			projID := strings.TrimSuffix(strings.TrimPrefix(target, "/projects/"), "/export")
			s.exportProjectsCSV(r.Context(), w, fy, projID)
		case target == "/ia/analytics/export":
			s.exportIAAnalyticsCSV(r.Context(), w, fy)
		default:
			http.Error(w, "Unknown export target", http.StatusNotFound)
		}
	})
}

// annexTarget is an impact report's evidence annex download.
var annexTarget = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/annex\.csv$`)

// releaseTarget is a released version's download.
var releaseTarget = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/releases/([A-Za-z0-9]{1,30})/download$`)

// exportPermission is the matrix's data.export.
const exportPermission = "data.export"

// organisationWideExport is an export that reads every school's, person's or
// project's records, with no limit to the reader's scope yet.
func organisationWideExport(target string) bool {
	switch target {
	case "/projects/export", "/ia/analytics/export":
		return true
	}
	return strings.HasPrefix(target, "/projects/") && strings.HasSuffix(target, "/export")
}

func startCSV(w http.ResponseWriter, filename string) *csv.Writer {
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	w.Header().Set("Cache-Control", "no-store")
	return csv.NewWriter(w)
}

func (s *Service) writeSchoolUploadTemplate(w http.ResponseWriter) {
	cw := startCSV(w, "edify-schools-upload-template.csv")
	_ = cw.Write([]string{
		"school_id", "school_name", "district", "sub_county", "parish",
		"school_type", "enrollment", "primary_contact_name", "primary_contact_phone",
		"school_phone", "shipping_address", "latitude", "longitude",
	})
	_ = cw.Write([]string{
		"1001", "Example Primary School", "Mukono", "Goma", "Nantabulirwa",
		"Client", "420", "Jane Doe", "+256700000000",
		"+256700000001", "Kampala-Jinja Highway", "", "",
	})
	cw.Flush()
}

func (s *Service) exportProjectsCSV(ctx context.Context, w http.ResponseWriter, fy, projectID string) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(pr.code, ''), pr.name, COALESCE(pr.category, ''), COALESCE(pr.status, ''),
       COALESCE(pr.budget_ceiling_ugx, 0),
       (SELECT count(*) FROM project_school_assignment psa WHERE psa.project_id = pr.id),
       (SELECT count(*) FROM activity a WHERE a.project_id = pr.id AND a.deleted_at IS NULL AND a.fy = $1),
       (SELECT count(*) FROM activity a WHERE a.project_id = pr.id AND a.deleted_at IS NULL AND a.fy = $1
         AND a.status IN ('completed', 'verified', 'approved', 'submitted'))
FROM project pr
WHERE pr.deleted_at IS NULL AND ($2 = '' OR pr.id = $2)
ORDER BY pr.name`, fy, projectID)
	if err != nil {
		http.Error(w, "Export query failed", http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	name := fmt.Sprintf("edify-projects-fy%s.csv", fy)
	if projectID != "" {
		name = fmt.Sprintf("edify-project-%s-fy%s.csv", projectID, fy)
	}
	cw := startCSV(w, name)
	_ = cw.Write([]string{"Project Code", "Project Name", "Category", "Status", "Budget Ceiling (UGX)", "Assigned Schools", "Total Activities", "Completed Activities"})
	for rows.Next() {
		var code, pname, cat, status string
		var ceiling, schools, acts, done int64
		if err := rows.Scan(&code, &pname, &cat, &status, &ceiling, &schools, &acts, &done); err == nil {
			_ = cw.Write([]string{code, pname, cat, status, strconv.FormatInt(ceiling, 10), strconv.FormatInt(schools, 10), strconv.FormatInt(acts, 10), strconv.FormatInt(done, 10)})
		}
	}
	cw.Flush()
}

func (s *Service) exportIAAnalyticsCSV(ctx context.Context, w http.ResponseWriter, fy string) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(sc.school_id, ''), sc.name, COALESCE(d.name, ''), sr.fy,
       COALESCE(sr.average_score, 0), COALESCE(sr.verification_status, '')
FROM ssa_record sr
JOIN school sc ON sc.id = sr.school_id
LEFT JOIN district d ON d.id = sc.district_id
WHERE sr.deleted_at IS NULL AND ($1 = '' OR sr.fy = $1)
ORDER BY sr.created_at DESC LIMIT 2000`, fy)
	if err != nil {
		http.Error(w, "Export query failed", http.StatusInternalServerError)
		return
	}
	defer rows.Close()
	cw := startCSV(w, fmt.Sprintf("edify-ia-analytics-fy%s.csv", fy))
	_ = cw.Write([]string{"School ID", "School Name", "District", "FY", "Overall SSA Score", "Verification Status"})
	for rows.Next() {
		var scode, sname, dist, rfy, status string
		var score float64
		if err := rows.Scan(&scode, &sname, &dist, &rfy, &score, &status); err == nil {
			_ = cw.Write([]string{scode, sname, dist, rfy, fmt.Sprintf("%.2f", score), status})
		}
	}
	cw.Flush()
}
