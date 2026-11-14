package schema

import "testing"

func TestTheShippedMigrationsPassTheLint(t *testing.T) {
	migrations, err := Spec.Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(migrations) == 0 || migrations[0].Version != 1 {
		t.Fatalf("want the migrations from 0001, got %+v", migrations)
	}
	for i, m := range migrations {
		if m.Version != i+1 || len(m.Checksum) != 64 {
			t.Fatalf("migration %q: version %d, checksum %q", m.Name, m.Version, m.Checksum)
		}
	}
}

func TestTheLintKeepsTheExistingTablesOutOfReach(t *testing.T) {
	for name, sql := range map[string]string{
		"the school table":          `ALTER TABLE school ADD COLUMN verified boolean;`,
		"the existing geo points":   `CREATE INDEX x ON school_geo_point (school_id);`,
		"a foreign key into public": `CREATE TABLE field_routes.a (id int REFERENCES school (id));`,
		"a grant to another role":   `GRANT SELECT ON field_routes.location_report TO edify_gateway;`,
	} {
		if err := Spec.Lint(sql); err == nil {
			t.Errorf("%s: the lint let it through", name)
		}
	}
}
