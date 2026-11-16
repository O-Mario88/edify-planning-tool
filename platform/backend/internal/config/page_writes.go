package config

import (
	"fmt"
	"slices"
	"strings"
)

// PageWrites names the pages whose read writes that Go builds, making the
// same writes the existing page's read makes (owner, 2026-11-16: "Same
// writes"; docs/migration/68 §68.7). Every such page is off, and passed on
// to the existing application, unless EDIFY_GO_PAGE_WRITES names it; the
// switch is refused outside development and staging.
type PageWrites struct {
	// MyProfessionalDevelopment: /my-professional-development moves the
	// reader's courses on by their dates, closes the reminders that ends,
	// and makes the year's allocation (internal/mypd).
	MyProfessionalDevelopment bool
}

const (
	envPageWrites = "EDIFY_GO_PAGE_WRITES"
	// PageWriteMyProfessionalDevelopment is the name EDIFY_GO_PAGE_WRITES
	// uses for My Professional Development.
	PageWriteMyProfessionalDevelopment = "my_professional_development"
)

var knownPageWrites = []string{PageWriteMyProfessionalDevelopment}

func loadPageWrites(env Environment, getenv func(string) string) (PageWrites, error) {
	names := splitList(getenv(envPageWrites))
	if len(names) == 0 {
		return PageWrites{}, nil
	}
	if env != Development && env != Staging {
		return PageWrites{}, fmt.Errorf("config: %s is refused in %s: pages that write run only in development or staging", envPageWrites, env)
	}
	var out PageWrites
	for _, name := range names {
		if !slices.Contains(knownPageWrites, name) {
			return PageWrites{}, fmt.Errorf("config: %s names %q; the pages Go can write from are %s",
				envPageWrites, name, strings.Join(knownPageWrites, ", "))
		}
		out.MyProfessionalDevelopment = out.MyProfessionalDevelopment || name == PageWriteMyProfessionalDevelopment
	}
	return out, nil
}

// Names are the pages that write, as EDIFY_GO_PAGE_WRITES names them.
func (w PageWrites) Names() []string {
	out := []string{}
	if w.MyProfessionalDevelopment {
		out = append(out, PageWriteMyProfessionalDevelopment)
	}
	return out
}
