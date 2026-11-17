package ownedschema

import (
	"testing"
	"testing/fstest"
)

var spec = Spec{Name: "things", OwnerRole: "edify_things_owner", WriterRole: "edify_things_rw",
	Files: fstest.MapFS{}, LockKey: 1}

// Row-level security is the one place the lint lets "security" through, and
// only in the exact statements that switch it on and the policies that
// compare a row's own columns with the session's settings.
func TestTheLintAllowsRowSecurityOnTheSchemasOwnTables(t *testing.T) {
	for name, sql := range map[string]string{
		"enabling it": `ALTER TABLE things.thing ENABLE ROW LEVEL SECURITY;`,
		"forcing it":  `ALTER TABLE ONLY things.thing FORCE ROW LEVEL SECURITY;`,
		"a read":      `CREATE POLICY thing_read ON things.thing FOR SELECT TO edify_things_rw, edify_things_owner USING (true);`,
		"a keyed write": `CREATE POLICY thing_insert ON things.thing FOR INSERT TO edify_things_rw
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));`,
		"an update": `CREATE POLICY thing_update ON things.thing AS RESTRICTIVE FOR UPDATE TO edify_things_owner
  USING (current_setting('edify.platform_write', true) = 'on') WITH CHECK (coalesce(current_setting('edify.platform_write', true), '') = 'on');`,
	} {
		if err := spec.Lint(sql); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestTheLintRefusesEveryWayAroundRowSecurity(t *testing.T) {
	for name, sql := range map[string]string{
		"switching it off":           `ALTER TABLE things.thing DISABLE ROW LEVEL SECURITY;`,
		"no longer forcing it":       `ALTER TABLE things.thing NO FORCE ROW LEVEL SECURITY;`,
		"on another schema's table":  `ALTER TABLE school ENABLE ROW LEVEL SECURITY;`,
		"a policy elsewhere":         `CREATE POLICY p ON school FOR SELECT TO edify_things_rw USING (true);`,
		"a policy for another role":  `CREATE POLICY p ON things.thing FOR SELECT TO edify_gateway USING (true);`,
		"a policy for everyone":      `CREATE POLICY p ON things.thing FOR SELECT TO public USING (true);`,
		"a policy with no role":      `CREATE POLICY p ON things.thing FOR SELECT USING (true);`,
		"a policy that reads tables": `CREATE POLICY p ON things.thing FOR SELECT TO edify_things_rw USING (EXISTS (SELECT 1 FROM school));`,
		"a policy that joins":        `CREATE POLICY p ON things.thing FOR SELECT TO edify_things_rw USING (id IN (things.a JOIN things.b))`,
		"a policy that calls code":   `CREATE POLICY p ON things.thing FOR SELECT TO edify_things_rw USING (pg_read_file('x') <> '');`,
		"a policy for deleting":      `CREATE POLICY p ON things.thing FOR DELETE TO edify_things_rw USING (true);`,
		"a policy for everything":    `CREATE POLICY p ON things.thing FOR ALL TO edify_things_rw USING (true);`,
		"a policy changed":           `ALTER POLICY p ON things.thing USING (true);`,
		"security in another place":  `ALTER TABLE things.thing OWNER TO edify_gateway, ENABLE ROW LEVEL SECURITY;`,
	} {
		if err := spec.Lint(sql); err == nil {
			t.Errorf("%s: the lint let it through", name)
		}
	}
}
