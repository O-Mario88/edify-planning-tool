package notificationcenter

import (
	"reflect"
	"strings"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestCategoriesAreWordedAsDjangosTitleFilterWordsThem(t *testing.T) {
	for in, want := range map[string]string{
		"availability":            "Availability",
		"acting_leadership":       "Acting_Leadership",
		"hr":                      "Hr",
		"business-transformation": "Business-Transformation",
		"o'neil's":                "O'Neil's",
		"2fa notice":              "2fa Notice",
		"ALL CAPS":                "All Caps",
		"":                        "",
	} {
		if got := djangoTitle(in); got != want {
			t.Errorf("djangoTitle(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestThePageAskedIsReadAsPythonsIntReadsIt(t *testing.T) {
	for in, want := range map[string]int{
		"": 1, "2": 2, " 3 ": 3, "+4": 4, "-1": 1, "0": 1, "abc": 1, "1_0": 10, "1__0": 1, "_1": 1, "1_": 1,
		"2.0": 1, "99999999999999999999": 1<<31 - 1, "-99999999999999999999": 1, "+": 1, "١": 1,
	} {
		if got := pageAsked(in); got != want {
			t.Errorf("pageAsked(%q) = %d, want %d", in, got, want)
		}
	}
}

func TestASearchEscapesTheLikeWildcardsAsDjangoDoes(t *testing.T) {
	for in, want := range map[string]string{
		"slo": "%slo%", "%": `%\%%`, "_": `%\_%`, `a\b`: `%a\\b%`,
	} {
		if got := likeContains(in); got != want {
			t.Errorf("likeContains(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestTheRaisedTimeIsWrittenInEastAfricaTime(t *testing.T) {
	at := time.Date(2026, 11, 2, 22, 5, 0, 0, time.UTC)
	if got := createdLabel(at); got != "Nov 3, 2026 01:05" {
		t.Errorf("createdLabel = %q", got)
	}
}

func TestThePagerListsTheSharedWindowOfPages(t *testing.T) {
	for _, c := range []struct {
		current, total int
		want           []int32
	}{
		{1, 2, []int32{1, 2}},
		{3, 7, []int32{1, 2, 3, 4, 5, 6, 7}},
		{1, 10, []int32{1, 2, 0, 10}},
		{5, 10, []int32{1, 0, 4, 5, 6, 0, 10}},
		{10, 10, []int32{1, 0, 9, 10}},
		{3, 10, []int32{1, 2, 3, 4, 0, 10}},
		{8, 10, []int32{1, 0, 7, 8, 9, 10}},
	} {
		if got := pageWindow(c.current, c.total); !reflect.DeepEqual(got, c.want) {
			t.Errorf("pageWindow(%d, %d) = %v, want %v", c.current, c.total, got, c.want)
		}
	}
	if pagerNumbers(1, 1) != nil {
		t.Error("a single page has no pager")
	}
}

func TestANotificationIsDrawnAsTheTemplateDrawsIt(t *testing.T) {
	base := row{id: "n1", title: "T", category: "hr", priority: "high", status: "unread", actionRequired: true,
		createdAt: time.Date(2026, 1, 5, 9, 0, 0, 0, time.UTC)}
	got := item(base)
	if got.GetPriorityLabel() != "High" || !got.GetUnread() || !got.GetActionRequired() || !got.GetCanMarkRead() ||
		!got.GetCanArchive() || got.GetCreatedLabel() != "Jan 5, 2026 12:00" || got.GetCategoryLabel() != "Hr" {
		t.Errorf("an unread notification: %v", got)
	}
	if got.GetTargetRoute() != "" || got.GetActionLabel() != "" || got.GetContextType() != "" {
		t.Errorf("no record, no button and no link: %v", got)
	}

	urgent := base
	urgent.priority, urgent.status, urgent.targetRoute = "urgent", "read", "/x"
	got = item(urgent)
	if got.GetPriorityLabel() != "Critical" || got.GetActionRequired() || got.GetCanMarkRead() || !got.GetCanArchive() ||
		got.GetActionLabel() != defaultActionLabel {
		t.Errorf("a read urgent notification with a record: %v", got)
	}

	archived := base
	archived.status, archived.contextType, archived.contextID = "archived", "activity", "None"
	got = item(archived)
	if got.GetCanArchive() || got.GetCanMarkRead() || got.GetContextId() != "None" {
		t.Errorf("an archived notification: %v", got)
	}
	if djangoText(nil) != "None" || text(nil) != "" {
		t.Error("a missing record id is written None, a missing body nothing")
	}
}

func TestAnAbsentStatusIsEveryLiveOneAndAnEmptyOneMatchesNothing(t *testing.T) {
	empty := ""
	where, args := listFilter("u", askedOf(&screensv1.GetNotificationCenterRequest{}))
	if !strings.Contains(where, "NOT (status = $2 OR resolved_at IS NOT NULL)") || args[1] != rules.Statuses.Archived {
		t.Errorf("absent status: %s %v", where, args)
	}
	where, args = listFilter("u", askedOf(&screensv1.GetNotificationCenterRequest{Status: &empty}))
	if !strings.Contains(where, "status = $2") || args[1] != "" {
		t.Errorf("empty status: %s %v", where, args)
	}
	where, args = listFilter("u", asked{status: "unread", priority: "high", category: "hr", q: "x", actionRequired: true})
	want := "recipient_id = $1 AND status = $2 AND priority = $3 AND category = $4 AND action_required AND " +
		"(UPPER(title::text) LIKE UPPER($5) OR UPPER(body::text) LIKE UPPER($5))"
	if where != want || len(args) != 5 || args[4] != "%x%" {
		t.Errorf("every filter:\n%s\n%v", where, args)
	}
}

func TestOnlyTheRolesThePageOpensForAreAnswered(t *testing.T) {
	if rules.Roles["ClusterLeader"].Page || !rules.Roles["CCEO"].Page || !rules.Roles["Admin"].Page {
		t.Fatal("the exported door changed; this test names the seed's roles")
	}
	if _, err := (&Service{}).Build(t.Context(), auth.Principal{Account: auth.Account{ActiveRole: "ClusterLeader"}}, nil); err != ErrNotAvailable {
		t.Errorf("ClusterLeader: %v", err)
	}
	if _, err := (&Service{}).Build(t.Context(), auth.Principal{Account: auth.Account{ActiveRole: "NoSuchRole"}}, nil); err != ErrNotAvailable {
		t.Errorf("an unknown role: %v", err)
	}
	acting := auth.Principal{Account: auth.Account{ActiveRole: "CCEO", InActingAppointment: true,
		Acting: &auth.ActingAppointment{ActingRole: "ClusterLeader"}}}
	if roleOf(acting) != "ClusterLeader" {
		t.Error("an acting appointment opens the page in its acting role")
	}
}

func TestMutedCategoriesAreAListOfWords(t *testing.T) {
	for in, want := range map[string][]string{"": {}, "null": {}, "[]": {}, `["hr","partner"]`: {"hr", "partner"}} {
		got, err := mutedOf([]byte(in))
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Errorf("mutedOf(%q) = %v, %v", in, got, err)
		}
	}
	if _, err := mutedOf([]byte(`[1]`)); err == nil {
		t.Error("a number is not a category")
	}
}

func TestEmailIsConfiguredOnlyWithTheProviderAndItsKey(t *testing.T) {
	env := func(values map[string]string) func(string) string {
		return func(k string) string { return values[k] }
	}
	if !EmailConfigured(env(map[string]string{"EMAIL_PROVIDER": "resend", "RESEND_API_KEY": "k"})) {
		t.Error("provider and key")
	}
	if EmailConfigured(env(map[string]string{"EMAIL_PROVIDER": "resend"})) ||
		EmailConfigured(env(map[string]string{"EMAIL_PROVIDER": "console", "RESEND_API_KEY": "k"})) {
		t.Error("without the key, or with another provider, no email goes out")
	}
}
