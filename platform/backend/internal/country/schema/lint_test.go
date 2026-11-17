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

// A school's or an account's country is a row here, never a column added to
// the existing application's tables.
func TestTheLintKeepsTheExistingTablesOutOfReach(t *testing.T) {
	for name, sql := range map[string]string{
		"a country column on the school":  `ALTER TABLE school ADD COLUMN country_id uuid;`,
		"a country column on the account": `ALTER TABLE staff_profile ADD COLUMN country_code varchar(2);`,
		"a foreign key into the school":   `CREATE TABLE country_registry.a (id varchar(30) REFERENCES school (id));`,
		"a grant to another role":         `GRANT SELECT ON country_registry.country TO edify_gateway;`,
	} {
		if err := Spec.Lint(sql); err == nil {
			t.Errorf("%s: the lint let it through", name)
		}
	}
}
