package schema

import (
	"strings"
	"testing"
)

func TestLintAcceptsTheShippedMigrations(t *testing.T) {
	migrations, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(migrations) == 0 || migrations[0].Version != 1 {
		t.Fatalf("want the migrations from 0001, got %+v", migrations)
	}
	for i, migration := range migrations {
		if migration.Version != i+1 {
			t.Fatalf("migration %q is version %d, want %d: versions run without gaps", migration.Name, migration.Version, i+1)
		}
		if len(migration.Checksum) != 64 {
			t.Fatalf("migration %q has no sha256 checksum", migration.Name)
		}
	}
}

func TestLintRefusesAnythingOutsideTheSchema(t *testing.T) {
	refused := map[string]string{
		"a table in public":           `CREATE TABLE public.visits (id int);`,
		"an unqualified table":        `CREATE TABLE visits (id int);`,
		"an index on an existing one": `CREATE INDEX x ON school (name);`,
		"altering an existing table":  `ALTER TABLE activity ADD COLUMN x int;`,
		"a foreign key into public":   `CREATE TABLE cluster_leadership.a (id int REFERENCES school (id));`,
		"the existing user table":     `CREATE TABLE cluster_leadership.a (id int); COMMENT ON TABLE "user" IS 'x';`,
		"a drop":                      `ALTER TABLE cluster_leadership.a DROP COLUMN b;`,
		"a truncate":                  `TRUNCATE cluster_leadership.a;`,
		"a delete":                    `DELETE FROM cluster_leadership.a;`,
		"a grant to another role":     `GRANT SELECT ON cluster_leadership.a TO edify_gateway;`,
		"a role membership":           `GRANT edify_cluster_owner TO edify_gateway;`,
		"a role change":               `SET ROLE omario;`,
		"a function body":             `CREATE FUNCTION cluster_leadership.f() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;`,
		"a data copy":                 `COPY cluster_leadership.a FROM '/etc/passwd';`,
		"an update of rows":           `UPDATE cluster_leadership.a SET b = 1;`,
		"a new schema":                `CREATE SCHEMA other;`,
	}
	for name, sql := range refused {
		t.Run(name, func(t *testing.T) {
			if err := Lint(sql); err == nil {
				t.Fatalf("Lint accepted %q", sql)
			}
		})
	}
}

func TestLintAcceptsTheSchemasOwnObjects(t *testing.T) {
	sql := strings.Join([]string{
		`-- a comment naming public.school is only a comment`,
		`CREATE TABLE cluster_leadership.a (id uuid PRIMARY KEY, b_id uuid REFERENCES cluster_leadership.b (id));`,
		`CREATE UNIQUE INDEX a_one ON cluster_leadership.a (id) WHERE id IS NOT NULL;`,
		`CREATE INDEX IF NOT EXISTS a_two ON cluster_leadership.a (b_id);`,
		`ALTER TABLE cluster_leadership.a ADD COLUMN c text NOT NULL DEFAULT '';`,
		`COMMENT ON TABLE cluster_leadership.a IS 'the portal''s own table';`,
		`GRANT SELECT, INSERT, UPDATE ON cluster_leadership.a TO edify_cluster_rw;`,
	}, "\n")
	if err := Lint(sql); err != nil {
		t.Fatalf("Lint refused the schema's own objects: %v", err)
	}
}
