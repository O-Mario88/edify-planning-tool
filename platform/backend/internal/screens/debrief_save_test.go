package screens

import (
	"context"
	"slices"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/debriefs"
)

type fakeDebriefer struct{ got []debriefs.DailyForm }

func (f *fakeDebriefer) SaveDaily(_ context.Context, _ auth.Principal, form debriefs.DailyForm, _ activities.Origin) (string, error) {
	f.got = append(f.got, form)
	return debriefs.SubmittedMessage, nil
}

func TestTheDailyDebriefFormSavesInGoWithoutDjango(t *testing.T) {
	d := &fakeDebriefer{}
	answer, err := NewService(nil).WithDailyDebrief(d).SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/debriefs/submit", Form: debriefs.DailyFormKey,
		Values: map[string]string{"activity_ids": "a1,a2", "what_went_well": "the head teacher came", "challenges_faced": "rain"},
	}))
	if err != nil || !answer.Msg.GetSaved() || len(d.got) != 1 {
		t.Fatalf("answer %v, %v, got %v", answer, err, d.got)
	}
	if f := d.got[0]; !slices.Equal(f.ActivityIDs, []string{"a1", "a2"}) || f.WentWell != "the head teacher came" || f.Challenges != "rain" || f.Autosave {
		t.Fatalf("form %+v", f)
	}
}

func TestAnotherFormOnTheDebriefPageIsNotTheDailyDebrief(t *testing.T) {
	d := &fakeDebriefer{}
	fetcher := &formFetcher{}
	_, _ = NewService(fetcher).WithDailyDebrief(d).SaveDrawer(personSaving(), connect.NewRequest(&screensv1.SaveDrawerRequest{
		Path: "/debriefs/submit", Form: debriefs.DailyFormKey}))
	if len(d.got) != 0 {
		t.Fatalf("Go saved with Django present: %v", d.got)
	}
}
