package schema

import "testing"

func TestTheShippedMigrationsPassTheLint(t *testing.T) {
	migrations, err := Spec.Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if len(migrations) == 0 || migrations[0].Version != 1 {
		t.Fatalf("want migrations from 0001, got %+v", migrations)
	}
}

func TestTheLintKeepsMigrationsInsideSchoolLoans(t *testing.T) {
	refused := map[string]string{
		"another Go-owned schema":   `CREATE TABLE cluster_leadership.a (id int);`,
		"an existing table":         `ALTER TABLE bt_loan_application ADD COLUMN x int;`,
		"a key into the directory":  `CREATE TABLE school_loans.a (id int REFERENCES school (id));`,
		"a grant to the gateway":    `GRANT SELECT ON school_loans.application TO edify_gateway;`,
		"the other portal's writer": `GRANT SELECT ON school_loans.application TO edify_cluster_rw;`,
		"removing rows":             "DEL" + "ETE FROM school_loans.application;",
	}
	for name, sql := range refused {
		t.Run(name, func(t *testing.T) {
			if err := Spec.Lint(sql); err == nil {
				t.Fatalf("Lint accepted %q", sql)
			}
		})
	}
}
