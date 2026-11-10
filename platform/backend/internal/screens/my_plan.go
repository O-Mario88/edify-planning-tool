package screens

import (
	"context"
	"net/url"
	"regexp"
	"strings"

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
	maxQueryValueLen = 128
)

var queryKey = regexp.MustCompile(`^[a-z][a-z_]{0,39}$`)

// The ticked rows a drawer opens with ("ids", "school_ids"): up to
// maxTickedIDs plain ids, comma-joined, as the web's bar for ticked rows
// sends them.
const maxTickedIDs = 200

var plainID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

func isIDList(key string) bool {
	return key == "ids" || strings.HasSuffix(key, "_ids")
}

func isPlainIDList(value string) bool {
	ids := strings.Split(value, ",")
	if len(ids) > maxTickedIDs {
		return false
	}
	for _, id := range ids {
		if !plainID.MatchString(id) {
			return false
		}
	}
	return true
}

// GetMyPlan returns My Plan as the web draws it for the reader.
func (s *Service) GetMyPlan(
	ctx context.Context, request *connect.Request[screensv1.GetMyPlanRequest],
) (*connect.Response[screensv1.GetMyPlanResponse], error) {
	query, err := pageQuery(ctx, request.Msg.GetQuery())
	if err != nil {
		return nil, err
	}
	path := pathMyPlan
	if len(query) > 0 {
		path += "?" + query.Encode()
	}
	return fetch[screensv1.GetMyPlanResponse](ctx, s, path)
}

// pageQuery is a page's own query, refused when a key is not a plain word or
// a value is too long. The feed decides which keys the page reads.
func pageQuery(ctx context.Context, given map[string]string) (url.Values, error) {
	if len(given) > maxQueryKeys {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This view cannot be opened.")
	}
	query := url.Values{}
	for key, value := range given {
		fits := len(value) <= maxQueryValueLen
		if isIDList(key) {
			fits = value == "" || isPlainIDList(value)
		}
		if !queryKey.MatchString(key) || !fits {
			return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This view cannot be opened.")
		}
		if value != "" {
			query.Set(key, value)
		}
	}
	return query, nil
}
