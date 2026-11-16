//go:build integration

package integration

import (
	"encoding/json"
	"os"
	"testing"
)

// The existing feed's User Management over the development seed: the
// Admin on each table page, with a search and each role and status filter,
// and the readers it refuses. Skipped unless EDIFY_ADMIN_USERS_GOLDEN names
// a file internal/adminusers/testdata/golden.py wrote.
func TestAdminUsersMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_USERS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_USERS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing of User Management")
	}
	compareGolden(t, "/admin-panel/users", golden.Answers)
}
