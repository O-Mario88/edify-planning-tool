package clusterpage

// What the cluster create drawer (internal/clustercreate) borrows from this
// page: what a role may do here.

// RoleDoors is what role may do on the page, by the page's own gates (a role
// the rules do not name may do nothing).
func RoleDoors(role string) Doors { return rules.Doors[role] }
