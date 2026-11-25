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

// notFound is an export's Http404: an error saying NotFound() true, for a
// record the reader does not see.
func notFound(err error) bool {
	var nf interface{ NotFound() bool }
	return errors.As(err, &nf) && nf.NotFound()
}

// WithWorkbook serves the export at target (a page's export path) from Go.
func (s *Service) WithWorkbook(target string, export WorkbookExport) *Service {
	if s.workbooks == nil {
		s.workbooks = map[string]WorkbookExport{}
	}
	s.workbooks[target] = export
	return s
}

// WorkbookRoute names the workbook export at a target matching a pattern
// (an export path carrying a record's id), or none.
type WorkbookRoute func(target string) (WorkbookExport, bool)

// WithWorkbookRoute serves the workbook exports a route names from Go.
func (s *Service) WithWorkbookRoute(route WorkbookRoute) *Service {
	s.workbookRoutes = append(s.workbookRoutes, route)
	return s
}

func (s *Service) workbookFor(target string) (WorkbookExport, bool) {
	if export, ok := s.workbooks[target]; ok {
		return export, true
	}
	for _, route := range s.workbookRoutes {
		if export, ok := route(target); ok {
			return export, true
		}
	}
	return nil, false
}

// serveWorkbook answers a workbook export Go takes, and says whether it did.
func (s *Service) serveWorkbook(w http.ResponseWriter, r *http.Request, p auth.Principal, target string) bool {
	export, ok := s.workbookFor(target)
	if !ok {
		return false
	}
	query := r.URL.Query()
	query.Del("target")
	stem, sheets, handled, err := export(r.Context(), p, query)
	switch {
	case errors.Is(err, pagegate.ErrNotAvailable), errors.Is(err, pagegate.ErrForbidden):
		http.Error(w, "You do not have access to this export.", http.StatusForbidden)
	case err != nil && handled && notFound(err):
		http.Error(w, err.Error(), http.StatusNotFound)
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

// FileExport builds one of the existing application's file exports that is
// not a workbook (a CSV written by the view itself): its file name and
// bytes. handled and err answer as WorkbookExport's do.
type FileExport func(ctx context.Context, p auth.Principal, query url.Values) (filename string, body []byte, handled bool, err error)

// WithFile serves the file export at target from Go.
func (s *Service) WithFile(target string, export FileExport) *Service {
	if s.files == nil {
		s.files = map[string]FileExport{}
	}
	s.files[target] = export
	return s
}

// serveFile answers a file export Go takes, and says whether it did.
func (s *Service) serveFile(w http.ResponseWriter, r *http.Request, p auth.Principal, target string) bool {
	export, ok := s.files[target]
	if !ok {
		return false
	}
	query := r.URL.Query()
	query.Del("target")
	name, body, handled, err := export(r.Context(), p, query)
	switch {
	case errors.Is(err, pagegate.ErrNotAvailable), errors.Is(err, pagegate.ErrForbidden):
		http.Error(w, "You do not have access to this export.", http.StatusForbidden)
	case err != nil:
		http.Error(w, "This export could not be made.", http.StatusInternalServerError)
	case !handled:
		http.Error(w, "This export is not available here yet. Use the Edify web app.", http.StatusServiceUnavailable)
	default:
		// The view's own content type: a CSV is "text/csv".
		w.Header().Set("Content-Type", "text/csv")
		w.Header().Set("Content-Disposition", `attachment; filename="`+name+`"`)
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write(body)
	}
	return true
}
