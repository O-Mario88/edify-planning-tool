package iaframework

import (
	"context"
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ssa_mapping_page: a reader who works the rules on the framework is sent
// there (RULES_URL), whatever the query, before the register is read.
func TestTheRulesRegisterSendsFrameworkReadersToTheirRules(t *testing.T) {
	s := &Service{}
	readers := 0
	for role, r := range rules.Roles {
		if !r.Mapping || !r.FrameworkReader {
			continue
		}
		readers++
		page, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: role}},
			MappingPath, url.Values{"rules_page": {"2"}})
		if err != nil || !served || page.GetRedirect() != "/ia/framework/?tab=rules" {
			t.Errorf("%s: %v %v %q", role, err, served, page.GetRedirect())
		}
	}
	if readers == 0 {
		t.Fatal("no role reads the rules on the framework")
	}
}
