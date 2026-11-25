package detailpages

import (
	"context"
	"errors"
	"net/http"
	"net/url"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// WorkbookExport builds one of the existing application's workbook exports
// for the reader from the page's own query: the file's stem and its sheets
// (apps.core.excel.table_download). handled is false when Go does not take
// the export for this reader; an error is the export's refusal.
type WorkbookExport func(ctx context.Context, p auth.Principal, query url.Values) (stem string, sheets []workbook.Sheet, handled bool, err error)

// WithWorkbook serves the export at target (a page's export path) from Go.
func (s *Service) WithWorkbook(target string, export WorkbookExport) *Service {
	if s.workbooks == nil {
		s.workbooks = map[string]WorkbookExport{}
	}
	s.workbooks[target] = export
	return s
}

// serveWorkbook answers a workbook export Go takes, and says whether it did.
func (s *Service) serveWorkbook(w http.ResponseWriter, r *http.Request, p auth.Principal, target string) bool {
	export, ok := s.workbooks[target]
	if !ok {
		return false
	}
	query := r.URL.Query()
	query.Del("target")
	stem, sheets, handled, err := export(r.Context(), p, query)
	switch {
	case errors.Is(err, pagegate.ErrNotAvailable), errors.Is(err, pagegate.ErrForbidden):
		http.Error(w, "You do not have access to this export.", http.StatusForbidden)
	case err != nil && handled:
		http.Error(w, err.Error(), http.StatusForbidden)
	case err != nil:
		http.Error(w, "This export could not be made.", http.StatusInternalServerError)
	case !handled:
		http.Error(w, "This export is not available here yet. Use the Edify web app.", http.StatusServiceUnavailable)
	default:
		w.Header().Set("Cache-Control", "no-store")
		if werr := workbook.Download(w, r, stem, sheets); werr != nil {
			http.Error(w, "This export could not be made.", http.StatusInternalServerError)
		}
	}
	return true
}
