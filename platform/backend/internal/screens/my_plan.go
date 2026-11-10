package screens

import (
	"context"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// My Plan, read by the existing application's own page (apps.mobile_feed
// MyPlanFeedView). The feed decides which of the page's parameters pass;
// the gateway only refuses a key that is not a plain word or a value that
// is too long, so nothing else of the existing application can be reached.

const (
	pathMyPlan       = "/api/mobile/v1/my-plan"
	maxQueryKeys     = 20
	maxQueryValueLen = 64
)

var queryKey = regexp.MustCompile(`^[a-z][a-z_]{0,39}$`)

// GetMyPlan returns My Plan as the web draws it for the reader.
func (s *Service) GetMyPlan(
	ctx context.Context, request *connect.Request[screensv1.GetMyPlanRequest],
) (*connect.Response[screensv1.GetMyPlanResponse], error) {
	given := request.Msg.GetQuery()
	if len(given) > maxQueryKeys {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This view of My Plan cannot be opened.")
	}
	query := url.Values{}
	for key, value := range given {
		if !queryKey.MatchString(key) || len(value) > maxQueryValueLen {
			return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This view of My Plan cannot be opened.")
		}
		if value != "" {
			query.Set(key, value)
		}
	}
	path := pathMyPlan
	if len(query) > 0 {
		path += "?" + query.Encode()
	}
	return fetch[screensv1.GetMyPlanResponse](ctx, s, path)
}
