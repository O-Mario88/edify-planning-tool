package notificationcenter

import (
	"reflect"
	"testing"
)

// The existing Category select lists a category once for every moment it was
// raised (values_list("category").distinct() under the model's ordering is
// distinct on category and time): admin@'s listed "Availability" 95 times. Go
// lists each once, newest first (owner, 2026-11-13: "Can you fix those from
// the go side"; intended.json go-fix-notification-categories).
func TestTheCategorySelectListsEachCategoryOnce(t *testing.T) {
	got := firstSeen([]string{"availability", "workflow", "availability", "", "planning", "workflow"})
	if want := []string{"availability", "workflow", "planning"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if got := firstSeen(nil); len(got) != 0 {
		t.Fatalf("no categories: %v", got)
	}
}
