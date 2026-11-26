package detailpages

import (
	"context"
	"errors"
	"mime"
	"net/http"
	"net/url"
	"path"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
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
	if err != nil {
		s.exportFailed(w, r, p, target, err)
		return true
	}
	switch {
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

// FileRoute names the file export of a target with ids in its path.
type FileRoute func(target string) (FileExport, bool)

// WithFileRoute serves the file exports a route names from Go.
func (s *Service) WithFileRoute(route FileRoute) *Service {
	s.fileRoutes = append(s.fileRoutes, route)
	return s
}

func (s *Service) fileFor(target string) (FileExport, bool) {
	if export, ok := s.files[target]; ok {
		return export, true
	}
	for _, route := range s.fileRoutes {
		if export, ok := route(target); ok {
			return export, true
		}
	}
	return nil, false
}

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
	export, ok := s.fileFor(target)
	if !ok {
		return false
	}
	query := r.URL.Query()
	query.Del("target")
	name, body, handled, err := export(r.Context(), p, query)
	if err != nil {
		s.exportFailed(w, r, p, target, err)
		return true
	}
	switch {
	case !handled:
		http.Error(w, "This export is not available here yet. Use the Edify web app.", http.StatusServiceUnavailable)
	default:
		// The view's own content type: a CSV is "text/csv"; a stored
		// document is its own kind (FileResponse's guess from its name).
		switch ext := strings.ToLower(path.Ext(name)); {
		case ext == ".xlsx":
			w.Header().Set("Content-Type", workbook.ContentType)
		case ext == ".csv" || ext == "":
			w.Header().Set("Content-Type", "text/csv")
		case mime.TypeByExtension(ext) != "":
			w.Header().Set("Content-Type", mime.TypeByExtension(ext))
		default:
			w.Header().Set("Content-Type", "application/octet-stream")
		}
		w.Header().Set("Content-Disposition", `attachment; filename="`+name+`"`)
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write(body)
	}
	return true
}

// exportFailed answers an export's error: the page gate's refusal, a
// refusal in the existing words, a record the reader does not see, or the
// export failing, which is logged and never shown.
func (s *Service) exportFailed(w http.ResponseWriter, r *http.Request, p auth.Principal, target string, err error) {
	var refusal workbook.Refusal
	var bad workbook.BadRequest
	switch {
	case errors.As(err, &bad):
		http.Error(w, string(bad), http.StatusBadRequest)
	case errors.Is(err, pagegate.ErrNotAvailable), errors.Is(err, pagegate.ErrForbidden):
		s.auditRefusal(r, p, target)
		http.Error(w, "You do not have access to this export.", http.StatusForbidden)
	case errors.As(err, &refusal):
		http.Error(w, string(refusal), http.StatusForbidden)
	case notFound(err):
		http.Error(w, err.Error(), http.StatusNotFound)
	default:
		if s.logger != nil {
			s.logger.ErrorContext(r.Context(), "detailpages: the export failed", "target", target, "err", err)
		}
		http.Error(w, "This export could not be made.", http.StatusInternalServerError)
	}
}

// auditRefusal writes the unauthorized_page_access row when the page gate
// refuses p the export's page. It is best-effort: a failure is logged and
// the refusal stands.
func (s *Service) auditRefusal(r *http.Request, p auth.Principal, target string) {
	pages := pageaccess.RefusedPages(p.ActiveRole, false, target)
	if len(pages) == 0 || s.refusals == nil || p.UserID == "" {
		return
	}
	o := origin.Read(r.RemoteAddr, r.Header, s.trustProxy, trace.FromContext(r.Context()).RequestID)
	err := audit.AppendRefusedPage(r.Context(), s.refusals, audit.RefusedPage{UserID: p.UserID, Role: p.ActiveRole, Pages: pages,
		IP: o.IP, UserAgent: o.UserAgent, CorrelationID: o.CorrelationID}, s.now())
	if err != nil && s.logger != nil {
		s.logger.ErrorContext(r.Context(), "detailpages: the refused export was not audited", "target", target, "err", err)
	}
}
