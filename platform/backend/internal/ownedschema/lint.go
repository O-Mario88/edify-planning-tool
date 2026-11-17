package ownedschema

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
)

// The lint is the second wall around the existing application's tables (the
// first is that the owner role holds no privilege on them). A migration may
// only create, alter, index, comment on and grant the schema's own tables,
// switch row-level security on for them and give them policies, and may
// never drop, truncate, delete, change roles or run code.

var (
	// Words no statement may hold, wherever they appear outside a quoted
	// string: data or objects destroyed, roles changed, code run.
	forbidden = regexp.MustCompile(`\b(drop|truncate|delete|role|copy|execute|security|schema)\b|\$\$|"user"|\bpublic\s*\.`)

	references = regexp.MustCompile(`\breferences ([a-z_."]+)`)
	spaces     = regexp.MustCompile(`\s+`)

	// A policy's expressions compare the row's own columns with the
	// session's settings: no table is read and only these functions run.
	readsTables = regexp.MustCompile(`\b(select|from|join)\b`)
	calls       = regexp.MustCompile(`([a-z_][a-z0-9_]*)\s*\(`)
	policyCalls = map[string]bool{"current_setting": true, "string_to_array": true, "coalesce": true,
		"any": true, "and": true, "or": true, "not": true, "in": true}
)

type linter struct {
	allowed []*regexp.Regexp
	whole   *regexp.Regexp
	// rowSecurity is the whole of a statement that switches row-level
	// security on; it is the only statement "security" may appear in.
	rowSecurity *regexp.Regexp
	// policy is a policy on the schema's own table, for reading, adding or
	// changing rows (never deleting), held by the writer or owner role.
	policy *regexp.Regexp
}

func (s Spec) linter() linter {
	qualified := regexp.QuoteMeta(s.Name) + `\.[a-z_][a-z0-9_]*`
	writer := regexp.QuoteMeta(s.WriterRole)
	ownRoles := `(` + writer + `|` + regexp.QuoteMeta(s.OwnerRole) + `)`
	return linter{
		allowed: []*regexp.Regexp{
			regexp.MustCompile(`^create table (if not exists )?` + qualified + ` \(`),
			regexp.MustCompile(`^create (unique )?index (if not exists )?[a-z_][a-z0-9_]* on (only )?` + qualified + ` \(`),
			regexp.MustCompile(`^alter table (if exists )?(only )?` + qualified + ` `),
			regexp.MustCompile(`^comment on (table ` + qualified + `|column ` + qualified + `\.[a-z_][a-z0-9_]*) is ''$`),
			regexp.MustCompile(`^grant (select|insert|update)(, (select|insert|update))* on (table )?` +
				qualified + `(, ` + qualified + `)* to ` + writer + `$`),
		},
		whole:       regexp.MustCompile(`^` + qualified + `$`),
		rowSecurity: regexp.MustCompile(`^alter table (only )?` + qualified + ` (enable|force) row level security$`),
		policy: regexp.MustCompile(`^create policy [a-z_][a-z0-9_]* on ` + qualified +
			` (as (permissive|restrictive) )?for (select|insert|update) to ` + ownRoles + `(, ` + ownRoles + `)?` +
			`( using \((?P<using>.*?)\))?( with check \((?P<check>.*)\))?$`),
	}
}

// Lint refuses SQL that reaches outside the schema or that destroys, changes
// roles or runs code.
func (s Spec) Lint(sql string) error {
	if err := s.check(); err != nil {
		return err
	}
	statements, err := statementsOf(sql)
	if err != nil {
		return err
	}
	if len(statements) == 0 {
		return errors.New("the migration holds no statement")
	}
	rules := s.linter()
	for _, statement := range statements {
		if rules.rowSecurity.MatchString(statement) {
			continue
		}
		if match := rules.policy.FindStringSubmatch(statement); match != nil {
			using, check := match[rules.policy.SubexpIndex("using")], match[rules.policy.SubexpIndex("check")]
			if err := policyExpressions(statement, using+" "+check); err != nil {
				return err
			}
		}
		if word := forbidden.FindString(statement); word != "" {
			return fmt.Errorf("%q is not allowed in a migration: %s", word, statement)
		}
		if !rules.matchesAny(statement) {
			return fmt.Errorf("only CREATE TABLE, CREATE INDEX, ALTER TABLE, COMMENT ON, GRANT to %s, row-level security and its policies on %s objects are allowed: %s",
				s.WriterRole, s.Name, statement)
		}
		for _, match := range references.FindAllStringSubmatch(statement, -1) {
			if !rules.whole.MatchString(match[1]) {
				return fmt.Errorf("a reference may only point inside %s: %s", s.Name, statement)
			}
		}
	}
	return nil
}

// policyExpressions refuses a policy whose expressions read a table or call
// anything but the few functions a comparison with a setting needs.
func policyExpressions(statement, expressions string) error {
	if strings.TrimSpace(expressions) == "" {
		return fmt.Errorf("a policy needs USING or WITH CHECK: %s", statement)
	}
	if word := readsTables.FindString(expressions); word != "" {
		return fmt.Errorf("a policy may not read tables (%q): %s", word, statement)
	}
	for _, call := range calls.FindAllStringSubmatch(expressions, -1) {
		if !policyCalls[call[1]] {
			return fmt.Errorf("a policy may not call %s: %s", call[1], statement)
		}
	}
	return nil
}

func (l linter) matchesAny(statement string) bool {
	if l.policy.MatchString(statement) {
		return true
	}
	for _, pattern := range l.allowed {
		if pattern.MatchString(statement) {
			return true
		}
	}
	return false
}

// statementsOf splits sql into lower-cased statements with single spacing,
// line comments removed and every quoted string emptied to a pair of single
// quotes (so a word inside a comment or a string is never read as SQL).
// Block comments are refused outright.
func statementsOf(sql string) ([]string, error) {
	var (
		statements []string
		current    strings.Builder
	)
	for index := 0; index < len(sql); index++ {
		char := sql[index]
		switch {
		case char == '-' && index+1 < len(sql) && sql[index+1] == '-':
			for index < len(sql) && sql[index] != '\n' {
				index++
			}
			current.WriteByte(' ')
		case char == '/' && index+1 < len(sql) && sql[index+1] == '*':
			return nil, errors.New("block comments are not allowed in a migration")
		case char == '\'':
			index++
			for ; index < len(sql); index++ {
				if sql[index] == '\'' {
					if index+1 < len(sql) && sql[index+1] == '\'' {
						index++
						continue
					}
					break
				}
			}
			if index >= len(sql) {
				return nil, errors.New("a quoted string is never closed")
			}
			current.WriteString("''")
		case char == ';':
			statements = appendStatement(statements, current.String())
			current.Reset()
		default:
			current.WriteByte(char)
		}
	}
	return appendStatement(statements, current.String()), nil
}

func appendStatement(statements []string, raw string) []string {
	statement := strings.TrimSpace(spaces.ReplaceAllString(strings.ToLower(raw), " "))
	statement = strings.ReplaceAll(statement, "( ", "(")
	if statement == "" {
		return statements
	}
	return append(statements, statement)
}
