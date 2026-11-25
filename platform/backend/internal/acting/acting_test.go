package acting

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func day(value string) time.Time {
	parsed, err := time.Parse("2006-01-02", value)
	if err != nil {
		panic(err)
	}
	return parsed
}

func TestThePolicyIsTheExistingOne(t *testing.T) {
	pl, ok := ByKey("acting_pl")
	if !ok || pl.AppointerRole != "Program Lead" || pl.AppointeeRole != "CCEO" || pl.ActingRole != "Program Lead" ||
		pl.ScopeType != ScopePLTeam || pl.Label != "Acting Program Lead" || pl.ShortLabel != "Acting PL" {
		t.Fatalf("acting_pl = %+v", pl)
	}
	cd, ok := ByKey("acting_cd")
	if !ok || cd.AppointerRole != "CountryDirector" || cd.AppointeeRole != "Program Lead" || cd.ScopeType != ScopeCountry {
		t.Fatalf("acting_cd = %+v", cd)
	}
	if _, ok := cd.Granted["withheld_permissions"]; !ok {
		t.Fatal("the export lost what an appointment withholds")
	}
}

func TestTodayIsKampalasDay(t *testing.T) {
	// 22:30 UTC on 31 October is already 1 November in Kampala.
	got := Today(time.Date(2026, 10, 31, 22, 30, 0, 0, time.UTC))
	if want := day("2026-11-01"); !got.Equal(want) {
		t.Fatalf("Today = %s, want %s", got, want)
	}
}

func TestAnAppointmentIsAWholeMonthFromThisOneToElevenAhead(t *testing.T) {
	today := day("2026-11-11")
	cases := []struct {
		month, refusal string
		start, end     string
	}{
		{month: "2026-11", start: "2026-11-01", end: "2026-11-30"},
		{month: "2027-02", start: "2027-02-01", end: "2027-02-28"},
		{month: "2027-10", start: "2027-10-01", end: "2027-10-31"},
		{month: "2027-11", refusal: "Appointments can be made up to 12 months ahead."},
		{month: "2026-10", refusal: "That month has ended. Choose this month or a later one."},
		{month: "October", refusal: "Choose the month the appointment is for."},
		{month: "2026-13", refusal: "Choose the month the appointment is for."},
	}
	for _, c := range cases {
		start, end, err := appointableMonth(c.month, today)
		if c.refusal != "" {
			if err == nil || err.Error() != c.refusal {
				t.Errorf("%s: err = %v, want %q", c.month, err, c.refusal)
			}
			continue
		}
		if err != nil || !start.Equal(day(c.start)) || !end.Equal(day(c.end)) {
			t.Errorf("%s: %s–%s, %v", c.month, start, end, err)
		}
	}
	options := monthOptions(today)
	if len(options) != 12 || options[0].Value != "2026-11" || options[11].Value != "2027-10" ||
		options[0].Label != "November 2026" || options[0].Effective != "November 1 – November 30, 2026" {
		t.Fatalf("options = %+v … %+v", options[0], options[len(options)-1])
	}
}

func TestTheStateIsTheDates(t *testing.T) {
	start, end := day("2026-11-01"), day("2026-11-30")
	for today, want := range map[string]string{
		"2026-10-31": stateUpcoming, "2026-11-01": stateActive, "2026-11-30": stateActive, "2026-12-01": stateExpired,
	} {
		if got := state(start, end, false, day(today)); got != want {
			t.Errorf("%s: %s, want %s", today, got, want)
		}
	}
	if got := state(start, end, true, day("2026-11-15")); got != stateCancelled {
		t.Errorf("cancelled: %s", got)
	}
}

func TestTheConfirmationIsTheWebsWords(t *testing.T) {
	pl, _ := ByKey("acting_pl")
	got := confirmationStatement(pl, "Sarah Nakato", day("2026-12-01"), day("2026-12-31"))
	want := "Sarah will receive Acting PL operational access for your entire PL team, including your own " +
		"operational scope, from December 1 through December 31. Your permanent PL role will remain unchanged."
	if got != want {
		t.Fatalf("\n got %q\nwant %q", got, want)
	}
	cd, _ := ByKey("acting_cd")
	if got := confirmationStatement(cd, "Ann", day("2026-12-01"), day("2026-12-31")); got !=
		"Ann will receive Acting CD operational access for the country from December 1 through December 31. "+
			"Your permanent Country Director role will remain unchanged." {
		t.Fatalf("country: %q", got)
	}
}

func lead(role string, roles ...string) auth.Principal {
	return auth.Principal{Account: auth.Account{UserID: "u-" + role, ActiveRole: role, Roles: roles}}
}

func TestOnlyAPermanentLeaderInTheirOwnRoleAppoints(t *testing.T) {
	if entry, ok := appointingPolicy(lead("Program Lead", "Program Lead")); !ok || entry.Key != "acting_pl" {
		t.Fatal("a Program Lead appoints an Acting Program Lead")
	}
	if entry, ok := appointingPolicy(lead("CountryDirector", "CountryDirector")); !ok || entry.Key != "acting_cd" {
		t.Fatal("a Country Director appoints an Acting Country Director")
	}
	if _, ok := appointingPolicy(lead("CCEO", "CCEO")); ok {
		t.Fatal("a CCEO appoints nobody")
	}
	if _, ok := appointingPolicy(lead("Program Lead", "CCEO")); ok {
		t.Fatal("a role the account does not hold appoints nobody")
	}
	acting := lead("Program Lead", "Program Lead")
	acting.InActingAppointment = true
	if _, ok := appointingPolicy(acting); ok {
		t.Fatal("nobody in an acting capacity appoints")
	}
}

func TestWhoMayCancelAndWhoMayMoveAMonth(t *testing.T) {
	appointment := Appointment{SeatID: "seat-pl", ByRole: "Program Lead", ScopeType: ScopePLTeam, Country: "Uganda"}
	theLead := lead("Program Lead", "Program Lead")
	leadSeat := &seat{StaffID: "seat-pl", Country: "Uganda"}
	if !mayManage(theLead, leadSeat, appointment) || !mayChangeMonth(theLead, leadSeat, appointment) {
		t.Fatal("the seat's leader cancels and moves their own appointment")
	}
	director := lead("CountryDirector", "CountryDirector")
	if !mayManage(director, &seat{StaffID: "seat-cd", Country: "Uganda"}, appointment) {
		t.Fatal("the country's Director cancels an Acting Program Lead in their country")
	}
	if mayChangeMonth(director, &seat{StaffID: "seat-cd", Country: "Uganda"}, appointment) {
		t.Fatal("only the appointing leader moves the month")
	}
	if mayManage(director, &seat{StaffID: "seat-cd", Country: "Kenya"}, appointment) {
		t.Fatal("another country's Director does not")
	}
	if !mayManage(lead("Admin", "Admin"), nil, appointment) {
		t.Fatal("an Admin can always stop delegated access")
	}
	if mayManage(lead("Program Lead", "Program Lead"), &seat{StaffID: "seat-other"}, appointment) {
		t.Fatal("another Program Lead does not")
	}
}

func TestWorkingInTheActingCapacityNeedsTheSwitchAndTheRoleItWasMadeFrom(t *testing.T) {
	appointment := &auth.ActingAppointment{AppointeeRole: "CCEO", InCapacity: true}
	cases := []struct {
		name   string
		a      *auth.ActingAppointment
		role   string
		acting bool
	}{
		{"switched on, in the role it was made from", appointment, "CCEO", true},
		{"switched to another role they hold", appointment, "ProjectCoordinator", false},
		{"switched off", &auth.ActingAppointment{AppointeeRole: "CCEO"}, "CCEO", false},
		{"no appointment today", nil, "CCEO", false},
	}
	for _, c := range cases {
		if got := c.a.WorkingIn(c.role); got != c.acting {
			t.Errorf("%s: %v, want %v", c.name, got, c.acting)
		}
	}
}

func TestRevisionTimeIsWrittenAsTheExistingCodeWritesIt(t *testing.T) {
	at := time.Date(2026, 11, 25, 7, 24, 48, 583098000, time.FixedZone("EAT", 3*3600))
	if got := pythonISO(at); got != "2026-11-25T04:24:48.583098+00:00" {
		t.Fatalf("got %s", got)
	}
	if got := pythonISO(time.Date(2026, 11, 25, 4, 0, 0, 0, time.UTC)); got != "2026-11-25T04:00:00+00:00" {
		t.Fatalf("got %s", got)
	}
}
