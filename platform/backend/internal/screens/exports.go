package screens

import (
	"context"
	"errors"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/exports"
)

// An export the reader asked for. When the native Go exports.Manager is wired,
// GetExport answers directly from Go with zero Django calls.

const pathExports = "/api/mobile/v1/exports/"

var exportJob = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// ExportStore authorizes and reads native Go export jobs.
type ExportStore interface {
	AuthorizeDownload(p auth.Principal, jobID string) (*exports.Job, error)
}

// WithExports serves ExportService.GetExport natively in Go.
func (s *Service) WithExports(store ExportStore) *Service {
	s.exports = store
	return s
}

// GetExport returns how the reader's export is coming along.
func (s *Service) GetExport(
	ctx context.Context, request *connect.Request[screensv1.GetExportRequest],
) (*connect.Response[screensv1.GetExportResponse], error) {
	jobID := request.Msg.GetJobId()
	if !exportJob.MatchString(jobID) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This export cannot be opened.")
	}
	if p, ok := auth.PrincipalFrom(ctx); ok && s.exports != nil {
		job, err := s.exports.AuthorizeDownload(p, jobID)
		if err != nil {
			switch {
			case errors.Is(err, exports.ErrForbidden):
				return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, "You are not authorized to open this export.")
			case errors.Is(err, exports.ErrNotFound):
				if s.existingApp == nil {
					return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This export could not be found.")
				}
			default:
				return nil, apierr.Internal(ctx, s.logger, err)
			}
		} else {
			status := string(job.Status)
			downloadURL := ""
			if job.Status == exports.StatusCompleted {
				status = "ready"
				downloadURL = "/api/v1/exports/" + job.ID + "/download"
			}
			return connect.NewResponse(&screensv1.GetExportResponse{
				Status:      status,
				Filename:    job.Filename(),
				Error:       job.Error,
				DownloadUrl: downloadURL,
			}), nil
		}
	}
	return fetch[screensv1.GetExportResponse](ctx, s, pathExports+jobID)
}
