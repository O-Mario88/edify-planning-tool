package mytargets

import "slices"

// What the MSCS save (internal/mscs) borrows from the page: who may open it
// (require_page_permission("my_target")).

// MayOpen is whether role may open My Targets.
func MayOpen(role string) bool { return slices.Contains(rules.PageRoles, role) }
