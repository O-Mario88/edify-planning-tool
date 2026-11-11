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
// and may never drop, truncate, delete, change roles or run code.

var (
	// Words no statement may hold, wherever they appear outside a quoted
	// string: data or objects destroyed, roles changed, code run.
	forbidden = regexp.MustCompile(`\b(drop|truncate|delete|role|copy|execute|security|schema)\b|\$\$|"user"|\bpublic\s*\.`)

	references = regexp.MustCompile(`\breferences ([a-z_."]+)`)
	spaces     = regexp.MustCompile(`\s+`)
)

type linter struct {
	allowed []*regexp.Regexp
	whole   *regexp.Regexp
}

func (s Spec) linter() linter {
	qualified := regexp.QuoteMeta(s.Name) + `\.[a-z_][a-z0-9_]*`
	writer := regexp.QuoteMeta(s.WriterRole)
	return linter{
		allowed: []*regexp.Regexp{
			regexp.MustCompile(`^create table (if not exists )?` + qualified + ` \(`),
			regexp.MustCompile(`^create (unique )?index (if not exists )?[a-z_][a-z0-9_]* on (only )?` + qualified + ` \(`),
			regexp.MustCompile(`^alter table (if exists )?(only )?` + qualified + ` `),
			regexp.MustCompile(`^comment on (table ` + qualified + `|column ` + qualified + `\.[a-z_][a-z0-9_]*) is ''$`),
			regexp.MustCompile(`^grant (select|insert|update)(, (select|insert|update))* on (table )?` +
				qualified + `(, ` + qualified + `)* to ` + writer + `$`),
		},
		whole: regexp.MustCompile(`^` + qualified + `$`),
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
		if word := forbidden.FindString(statement); word != "" {
			return fmt.Errorf("%q is not allowed in a migration: %s", word, statement)
		}
		if !rules.matchesAny(statement) {
			return fmt.Errorf("only CREATE TABLE, CREATE INDEX, ALTER TABLE, COMMENT ON and GRANT to %s on %s objects are allowed: %s",
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

func (l linter) matchesAny(statement string) bool {
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
