package qualityflags

import (
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func str(s string) *string { return &s }

func TestPriorityIsWrittenAsDjangosTitleFilterWritesIt(t *testing.T) {
	for in, want := range map[string]string{"high": "High", "normal": "Normal", "very-high": "Very-High", "o'neil": "O'Neil", "don't": "Don't", "p1x": "P1x", "": ""} {
		if got := pyTitle(in); got != want {
			t.Errorf("pyTitle(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestAnOpenFlagOffersResolveFromItsMenuAndAnAcknowledgedOneAsAButton(t *testing.T) {
	pl := auth.Principal{UserID: "pl", ActiveRole: roleProgrammeLead}
	open := actions(pl, flag{ID: "f1", AssignedTo: "pl", Status: "open"}).GetActions()
	if len(open) != 1 || open[0].GetKey() != "menu" || open[0].GetPrimary() || open[0].GetHref() != "/quality-checks?resolve=f1" || !open[0].GetDrawer() {
		t.Fatalf("open flag actions: %v", open)
	}
	acked := actions(pl, flag{ID: "f2", AssignedTo: "pl", Status: "acknowledged"}).GetActions()
	if len(acked) != 1 || acked[0].GetKey() != "button" || !acked[0].GetPrimary() {
		t.Fatalf("acknowledged flag actions: %v", acked)
	}
	if got := actions(pl, flag{AssignedTo: "pl", Status: "resolved"}).GetActions(); len(got) != 0 {
		t.Fatalf("a resolved flag offers %v", got)
	}
	if got := actions(pl, flag{AssignedTo: "other", Status: "open"}).GetActions(); len(got) != 0 {
		t.Fatalf("another lead's flag offers %v", got)
	}
	admin := auth.Principal{UserID: "a", ActiveRole: roleAdmin}
	if got := actions(admin, flag{AssignedTo: "other", Status: "open"}).GetActions(); len(got) != 1 {
		t.Fatalf("Admin is offered %v on another lead's flag", got)
	}
}

func TestARowWritesEachCellAsTheRegisterDoes(t *testing.T) {
	at := time.Date(2026, 11, 13, 22, 30, 0, 0, time.UTC) // 14 Nov in Nairobi
	f := flag{Category: "data-quality", Note: "Check\n  the  scores", RecommendedAction: str("Re-enter"), Priority: "high",
		Status: "acknowledged", RaisedByName: str("Sarah"), CreatedAt: at}
	cells := row(auth.Principal{}, Role{Acts: false}, f).GetCells()
	want := []string{"data-quality", "Check the scores · Re-enter", "Sarah · 14 Nov 2026", "—", "High", "—", "Acknowledged", "—"}
	if len(cells) != len(want) {
		t.Fatalf("%d cells, want %d", len(cells), len(want))
	}
	for i, w := range want {
		if cells[i].GetText() != w {
			t.Errorf("cell %d = %q, want %q", i, cells[i].GetText(), w)
		}
	}
	if name(flag{ScopeName: str("")}) != "Flag" || name(flag{ScopeName: str("Kasana"), Category: "x"}) != "Kasana" {
		t.Error("the flag's name is not firstof scope_name, category, \"Flag\"")
	}
}

func TestTheFormCarriesWhatTheDrillDownHandedIt(t *testing.T) {
	q := url.Values{"scope_name": {"  Kasana PS "}, "assign_to": {"l2"}, "note": {"Look"}, "category": {"cat"}}
	form := raiseForm([]lead{{"l1", "A"}, {"l2", "B"}}, q).GetForm()
	items := form.GetItems()
	if items[0].GetText() != "About: Kasana PS" || items[2].GetField().GetValue() != "l2" || len(items[2].GetField().GetOptions()) != 3 {
		t.Fatalf("form items: %v", items)
	}
	if items[3].GetField().GetValue() != "cat" || items[4].GetField().GetValue() != "Look" {
		t.Fatalf("prefill: %v", items)
	}
	plain := raiseForm(nil, url.Values{"assign_to": {"nobody"}}).GetForm().GetItems()
	if plain[0].GetField().GetName() != "assigned_to_user_id" || plain[0].GetField().GetValue() != "" {
		t.Fatalf("form without a drill-down: %v", plain)
	}
}

func TestTheEmptyRegisterIsOneCell(t *testing.T) {
	blocks := register(auth.Principal{}, Role{Acts: true}, nil)
	table := blocks[1].GetTable()
	if table.GetEmptyMessage() != "No quality flags raised" || len(table.GetColumns()) != 0 || len(table.GetRows()) != 1 {
		t.Fatalf("empty register: %v", table)
	}
}
