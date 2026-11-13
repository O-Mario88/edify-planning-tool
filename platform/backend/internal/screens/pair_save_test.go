package screens

import (
	"fmt"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

// docs/migration/32: the In-school Training pair has its own switch, so
// naming one save never moves the other.

const pairForm = `{"form": {"school_id": "FEED-1", "purpose_of_visit": "in_school_training_ssa",
 "scheduled_date": "2026-11-24", "require_catalogue": "yes", "delivery_type": "staff",
 "executor_type": "staff", "catalogue_item_id": "course-1", "facilitating_partner_id": "",
 "activity_purpose_text": "a goal", "csrfmiddlewaretoken": "t"},
 "origin": {"ip": "127.0.0.1", "agent": "Go-http-client/1.1", "correlation": "c1"}}`

func TestEachScheduleSwitchMovesOnlyItsOwnSave(t *testing.T) {
	pairWords := "In-school training and school visit with SSA collection scheduled. It is on your My Plan — keep planning."
	tests := []struct {
		name, form    string
		visits, pairs bool
		wantGo        bool
	}{
		{name: "a visit with only the pair's switch", form: visitForm, pairs: true},
		{name: "a pair with only the visit's switch", form: pairForm, visits: true},
		{name: "a pair with its own switch", form: pairForm, pairs: true, wantGo: true},
		{name: "a visit with its own switch", form: visitForm, visits: true, wantGo: true},
		{name: "a pair with a partner facilitating", pairs: true,
			form: `{"form": {"school_id": "FEED-1", "purpose_of_visit": "in_school_training", "require_catalogue": "yes",
 "catalogue_item_id": "course-1", "facilitating_partner_id": "partner-1"}, "origin": {}}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fetcher := &formFetcher{form: test.form}
			saver := &fakeSaver{answer: activities.Answer{Message: pairWords}}
			service := NewService(fetcher)
			if test.visits {
				service.WithVisitSave(saver, nil)
			}
			if test.pairs {
				service.WithTrainingPairSave(saver, nil)
			}

			answer, err := saveSchedule(t, service, signedIn())

			if err != nil {
				t.Fatal(err)
			}
			if test.wantGo != (len(saver.got) == 1) {
				t.Fatalf("Go made %d saves, want Go %v", len(saver.got), test.wantGo)
			}
			forwarded := fmt.Sprint(fetcher.paths) ==
				"[POST /api/mobile/v1/schools/s1/planning/schedule?form_only=1 POST /api/mobile/v1/schools/s1/planning/schedule]"
			if test.wantGo == forwarded || (!test.wantGo && answer.GetMessage() != "forwarded") {
				t.Fatalf("asked %v, answered %v (a save is never made by both)", fetcher.paths, answer)
			}
		})
	}
}
