// Package rbac is the existing role → permission matrix, read by Go (owner
// brief, 2026-11-11: "Roles and permission management"). The matrix is the
// existing application's apps/core/rbac.py ROLE_PERMISSIONS, exported to
// role_permissions.json by `manage.py export_rbac_matrix`; a test there fails
// when the two differ, so Go never checks a different matrix.
package rbac

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

// Roles of the existing system (EdifyRole values) that Go's own rules name.
const (
	Admin            = "Admin"
	CCEO             = "CCEO"
	ProgramLead      = "Program Lead"
	ClusterLeader    = "ClusterLeader"
	ImpactAssessment = "ImpactAssessment"
)

// Permission keys Go's own rules check.
const (
	UserManage        = "user.manage"
	PartnerUserManage = "partnerUser.manage"
)

//go:embed role_permissions.json
var exported []byte

type document struct {
	Roles       []string            `json:"roles"`
	Permissions []string            `json:"permissions"`
	Grants      map[string][]string `json:"grants"`
}

var matrix = mustLoad(exported)

func mustLoad(raw []byte) document {
	var doc document
	if err := json.Unmarshal(raw, &doc); err != nil {
		panic(fmt.Sprintf("rbac: role_permissions.json is not readable: %v", err))
	}
	if len(doc.Roles) == 0 || len(doc.Grants) == 0 {
		panic("rbac: role_permissions.json holds no roles")
	}
	return doc
}

// Roles is every role the existing system defines, in its order.
func Roles() []string { return slices.Clone(matrix.Roles) }

// IsRole says whether role is one the existing system defines.
func IsRole(role string) bool { return slices.Contains(matrix.Roles, role) }

// PermissionsFor is permissions_for_role: the keys a role grants, sorted; an
// unknown role grants nothing.
func PermissionsFor(role string) []string { return slices.Clone(matrix.Grants[role]) }

// Grants says whether role holds permission.
func Grants(role, permission string) bool {
	_, found := slices.BinarySearch(matrix.Grants[role], permission)
	return found
}

// AdminIsAlsoCCEO is the existing admin_is_also_cceo: an Admin account is
// never a CCEO (owner, 2026-10-02).
func AdminIsAlsoCCEO(roles []string) bool {
	return slices.Contains(roles, Admin) && slices.Contains(roles, CCEO)
}
