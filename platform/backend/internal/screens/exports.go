package screens

import (
	"context"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// An export the reader asked for, read from the existing application's own
// export job (apps.mobile_feed.exports). The feed decides whose job it is;
// the gateway only refuses an id that is not a plain id.

const pathExports = "/api/mobile/v1/exports/"

var exportJob = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// GetExport returns how the reader's export is coming along.
func (s *Service) GetExport(
	ctx context.Context, request *connect.Request[screensv1.GetExportRequest],
) (*connect.Response[screensv1.GetExportResponse], error) {
	job := request.Msg.GetJobId()
	if !exportJob.MatchString(job) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This export cannot be opened.")
	}
	return fetch[screensv1.GetExportResponse](ctx, s, pathExports+job)
}
