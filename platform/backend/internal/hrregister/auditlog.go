package hrregister

import (
	"context"
	"fmt"
	"strings"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"
)

// auditShown is how many of the latest events the HR audit log lists.
const auditShown = 200

// hrAuditPrefixes are the actions the HR trail holds (HR, professional
// development, leave, policy documents, accounts and supervisors).
var hrAuditPrefixes = []string{"hr.", "pd.", "pd_", "leave.", "documents.", "admin.user", "admin.supervisor"}

// auditAreas name an action's area ("hr.er_case_opened" reads "HR · Er case
// opened").
var auditAreas = map[string]string{
	"hr": "HR", "pd": "Professional development", "leave": "Leave", "documents": "Policy", "admin": "Accounts",
}

// pyTitle is Python's str.title: each cased letter after an uncased
// character upper case, every other one lower case.
func pyTitle(s string) string {
	var b strings.Builder
	prevCased := false
	for _, r := range s {
		cased := unicode.IsUpper(r) || unicode.IsLower(r) || unicode.IsTitle(r)
		switch {
		case cased && !prevCased:
			b.WriteRune(unicode.ToTitle(r))
		case cased:
			b.WriteRune(unicode.ToLower(r))
		default:
			b.WriteRune(r)
		}
		prevCased = cased
	}
	return b.String()
}

// auditActionLabel is _audit_action_label: the action's area and its name,
// made readable.
func auditActionLabel(action string) string {
	area, name, _ := strings.Cut(action, ".")
	words := name
	if words == "" {
		words = area
	}
	words = strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(words, "_", " "), ".", " "))
	if words == "" {
		return dash(action)
	}
	label, ok := auditAreas[area]
	if !ok {
		label = pyTitle(area)
	}
	first := []rune(words)
	return label + " · " + strings.ToUpper(string(first[0])) + string(first[1:])
}

// hrAuditLog is hr_audit_log_view: the HR trail of the tamper-evident audit
// chain (every reader of the page reads all of it) whose action, acting role,
// subject id or subject kind holds the search, the latest 200, each with the
// actor's name when a live People record names them (else their id, else
// "System"), the time in UTC as the view writes it; the figures over every
// matching event.
func hrAuditLog(ctx context.Context, in input) (register, error) {
	args := []any{}
	prefixes := []string{}
	for _, p := range hrAuditPrefixes {
		args = append(args, likeStarts(p))
		prefixes = append(prefixes, fmt.Sprintf("a.action LIKE $%d", len(args)))
	}
	searchSQL, args := contains(in.search, args, "a.action", "a.actor_role", "a.subject_id", "a.subject_kind")
	where := fmt.Sprintf("(%s) AND %s", strings.Join(prefixes, " OR "), searchSQL)
	var total, refused, roles int
	if err := in.db.QueryRow(ctx, `
SELECT count(*), count(*) FILTER (WHERE NOT a.success), count(DISTINCT COALESCE(a.actor_role, '')) + 
       (CASE WHEN bool_or(a.actor_role IS NULL) AND bool_or(a.actor_role = '') THEN 1 ELSE 0 END)
FROM audit_log a WHERE `+where, args...).Scan(&total, &refused, &roles); err != nil {
		return register{}, fmt.Errorf("hrregister: counting the HR trail: %w", err)
	}
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT a.action, a.actor_id, (SELECT u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
                              WHERE sp.user_id = a.actor_id AND sp.deleted_at IS NULL LIMIT 1),
       COALESCE(a.actor_role, ''), COALESCE(a.subject_kind, ''), COALESCE(a.subject_id, ''), a.success, a.created_at
FROM audit_log a WHERE %s ORDER BY a.created_at DESC LIMIT %d`, where, auditShown), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the HR trail: %w", err)
	}
	type event struct {
		action, role, kind, subject string
		actor, name                 *string
		success                     bool
		at                          time.Time
	}
	events, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (event, error) {
		var e event
		err := row.Scan(&e.action, &e.actor, &e.name, &e.role, &e.kind, &e.subject, &e.success, &e.at)
		return e, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the HR trail: %w", err)
	}
	reg := register{
		path: "/hr-audit-log", title: "HR System Audit Log", eyebrow: "Policy and compliance",
		description: "Sensitive people decisions as recorded on the platform's tamper-evident, hash-chained audit trail. " +
			"Payload detail stays out of the list to limit incidental PII exposure.",
		columns:    []string{"Action", "Actor", "Role", "Record", "Outcome", "Timestamp"},
		emptyTitle: "No HR audit events recorded yet",
		emptyBody:  defaultEmptyBody,
	}
	for _, e := range events {
		actor := "System"
		switch {
		case e.name != nil:
			actor = *e.name
		case e.actor != nil && *e.actor != "":
			actor = *e.actor
		}
		outcome := "Refused"
		if e.success {
			outcome = "Success"
		}
		reg.rows = append(reg.rows, []string{
			auditActionLabel(e.action), dash(actor), dash(e.role), dash(e.kind) + " · " + dash(e.subject), outcome,
			e.at.UTC().Format("02 Jan 2006, 15:04"),
		})
	}
	reg.metrics = []metric{
		{"Events", count(total), "matching audit records", "info"},
		{"Refused actions", count(refused), "denied or blocked attempts", "warning"},
		{"Acting roles", count(roles), "roles represented", "info"},
		{"Showing", count(min(total, auditShown)), "most recent events", "info"},
	}
	return reg, nil
}

// likeStarts is Django's startswith as a LIKE pattern: the text, its own
// wildcards escaped, then anything.
func likeStarts(text string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return r.Replace(text) + "%"
}
