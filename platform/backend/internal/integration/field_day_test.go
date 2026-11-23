//go:build integration

package integration

import (
	"context"
	"net/http"
	"testing"
	"time"

	"connectrpc.com/connect"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1/routesv1connect"
)

// An officer's day in the field: save the order, start, arrive at a school,
// leave it, end. Arriving used to fail with a server error, because the stop's
// INSERT used one parameter as two different types.
func TestAFieldDayRecordsArrivingAndLeavingASchool(t *testing.T) {
	ctx := context.Background()
	var schoolID, userID string
	if err := admin.QueryRow(ctx, `
SELECT s.id, u.id FROM school s JOIN staff_profile sp ON sp.id = s.account_owner_id JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND s.deleted_at IS NULL AND s.closed_at IS NULL ORDER BY s.id LIMIT 1`).Scan(&schoolID, &userID); err != nil {
		t.Skip("the seeded officer holds no school")
	}
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	client := routesv1connect.NewRoutePlannerServiceClient(http.DefaultClient, baseURL)
	today := time.Now().In(time.FixedZone("EAT", 3*60*60)).Format(time.DateOnly)
	clean := func() {
		for _, table := range []string{"field_routes.field_day_stop", "field_routes.field_day"} {
			if _, err := admin.Exec(context.Background(), `DELETE FROM `+table+` WHERE user_id = $1 AND day = $2::date`, userID, today); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clean()
	t.Cleanup(clean)

	if _, err := client.SaveFieldDay(ctx, authed(&routesv1.SaveFieldDayRequest{Date: today, SchoolIds: []string{schoolID}}, token)); err != nil {
		if connect.CodeOf(err) == connect.CodeUnavailable {
			t.Skip("field days are not set up on this gateway")
		}
		t.Fatalf("saving the day: %v", err)
	}
	record := func(event, school string) *routesv1.SavedFieldDay {
		t.Helper()
		answer, err := client.RecordFieldDay(ctx, authed(&routesv1.RecordFieldDayRequest{Date: today, Event: event, SchoolId: school}, token))
		if err != nil {
			t.Fatalf("%s: %v", event, err)
		}
		return answer.Msg.GetSaved()
	}
	record("start", "")
	arrived := record("arrive", schoolID)
	if len(arrived.GetStops()) != 1 || arrived.GetStops()[0].GetArrivedAt() == "" {
		t.Fatalf("after arriving: %v", arrived.GetStops())
	}
	left := record("leave", schoolID)
	if left.GetStops()[0].GetLeftAt() == "" {
		t.Fatalf("after leaving: %v", left.GetStops())
	}
	if ended := record("end", ""); ended.GetEndedAt() == "" {
		t.Fatal("the day did not end")
	}
}
