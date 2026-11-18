package schoolimport

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// What a row comes to.
const (
	// Ready rows would add a new school.
	Ready = "ready"
	// Existing rows name a School ID a school of the country already holds:
	// an import would update that school, never give it another ID.
	Existing = "existing"
	// Duplicate rows repeat a School ID an earlier row of the file gave.
	Duplicate = "duplicate"
	// Rejected rows cannot be imported; their messages say why.
	Rejected = "rejected"
	// Skipped rows are blank.
	Skipped = "skipped"
)

var spaced = regexp.MustCompile(`[\s_\-]+`)

// normalizeHeader is the existing upload's header rule
// (apps/schools/upload_mapping.normalize_header): no BOM, lower case, "&"
// as "and", runs of spaces, underscores and hyphens as one space.
func normalizeHeader(raw string) string {
	h := strings.ToLower(strings.TrimSpace(strings.ReplaceAll(raw, "\uFEFF", "")))
	h = strings.ReplaceAll(h, "&", " and ")
	return strings.TrimSpace(spaced.ReplaceAllString(h, " "))
}

// headerFields are the existing upload's columns other than geography
// (SCHOOL_HEADER_MAP), and the national school ID's.
var headerFields = map[string]string{
	"school id": "school_id", "schoolid": "school_id",
	"school name": "name", "name": "name",
	"current partner type": "school_type", "partner type": "school_type", "school type": "school_type",
	"enrolment": "enrollment", "enrollment": "enrollment",
	"phone": "school_phone", "school phone": "school_phone",
	"national school id": "national_id", "national id": "national_id", "emis": "national_id",
	"emis number": "national_id", "emis code": "national_id", "government school id": "national_id",
}

// schoolTypes are the programmes' school types by their labels
// (SCHOOL_TYPE_MAP); the retired labels map as there.
var schoolTypes = map[string]string{
	"champion": "champion", "client": "client", "core": "core", "core graduate": "core_graduate",
	"core trained": "core_trained", "potential core": "core_trained", "potential champion": "champion",
}

// Level is one of the country's live levels.
type Level struct {
	ID, Canonical, Label string
	Number               int
	Required             bool
}

type unit struct {
	id, typeID, parentID, name string
}

// Place is the geography a preview places rows in, and what the country
// already holds: read once for a whole file.
type Place struct {
	Levels []Level
	units  []unit
	byID   map[string]unit
	// byName is the units of each level by their name's key.
	byName map[string]map[string][]unit
	// held is the School IDs a school already holds: true when it is a
	// school of this country.
	held map[string]bool
	// names is the keys of the names of the country's schools.
	names map[string]bool
}

// LoadPlace reads the country's live levels and units, and which of ids its
// schools or other countries' schools already hold.
func LoadPlace(ctx context.Context, q registry.Querier, countryID string, ids []string) (*Place, error) {
	p := &Place{byID: map[string]unit{}, byName: map[string]map[string][]unit{}, held: map[string]bool{}, names: map[string]bool{}}
	rows, err := q.Query(ctx, `SELECT id::text, canonical_type, local_label, level, is_required
FROM country_registry.admin_unit_type WHERE country_id = $1::uuid AND effective_to IS NULL ORDER BY level`, countryID)
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the levels: %w", err)
	}
	p.Levels, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (Level, error) {
		var l Level
		var n int16
		err := row.Scan(&l.ID, &l.Canonical, &l.Label, &n, &l.Required)
		l.Number = int(n)
		return l, err
	})
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the levels: %w", err)
	}
	rows, err = q.Query(ctx, `SELECT id::text, type_id::text, COALESCE(parent_id::text, ''), official_name
FROM country_registry.admin_unit WHERE country_id = $1::uuid AND valid_to IS NULL`, countryID)
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the units: %w", err)
	}
	p.units, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (unit, error) {
		var u unit
		return u, row.Scan(&u.id, &u.typeID, &u.parentID, &u.name)
	})
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the units: %w", err)
	}
	for _, u := range p.units {
		p.byID[u.id] = u
		if p.byName[u.typeID] == nil {
			p.byName[u.typeID] = map[string][]unit{}
		}
		key := lookupKey(u.name)
		p.byName[u.typeID][key] = append(p.byName[u.typeID][key], u)
	}
	rows, err = q.Query(ctx, `SELECT s.school_id, `+registry.SchoolHeldIn("s", "ARRAY[$1::text]")+`
FROM school s WHERE s.deleted_at IS NULL AND s.school_id = ANY($2)`, countryID, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the School IDs held: %w", err)
	}
	for rows.Next() {
		var id string
		var here bool
		if err := rows.Scan(&id, &here); err != nil {
			rows.Close()
			return nil, fmt.Errorf("schoolimport: reading the School IDs held: %w", err)
		}
		p.held[id] = p.held[id] || here
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("schoolimport: reading the School IDs held: %w", err)
	}
	rows, err = q.Query(ctx, `SELECT DISTINCT lower(btrim(s.name)) FROM school s
WHERE s.deleted_at IS NULL AND `+registry.SchoolHeldIn("s", "ARRAY[$1::text]"), countryID)
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the schools' names: %w", err)
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("schoolimport: reading the schools' names: %w", err)
	}
	for _, n := range names {
		p.names[n] = true
	}
	return p, nil
}

func lookupKey(value string) string { return strings.ToLower(strings.TrimSpace(value)) }

// Result is a preview of a whole file.
type Result struct {
	Rows []RowResult
	// Columns are the file's columns as read: what each one was taken as,
	// "" for a column not used.
	Columns []Column
	Counts  map[string]int
}

// Column is one header of the file and what it was taken as.
type Column struct {
	Header, TakenAs string
}

// RowResult is what one row comes to.
type RowResult struct {
	Line                               int
	SchoolID, Name, NationalID, Status string
	SchoolType                         string
	// Units are the names of the units the row is placed in, top first.
	Units    []string
	Messages []string
}

// SchoolIDs are the School IDs the sheet gives, for LoadPlace.
func SchoolIDs(s Sheet) []string {
	index := fieldIndex(s.Headers, nil)
	at, ok := index["school_id"]
	if !ok {
		return []string{}
	}
	seen := map[string]bool{}
	out := []string{}
	for _, r := range s.Rows {
		if at < len(r.Cells) {
			if id := strings.TrimSpace(r.Cells[at]); id != "" && !seen[id] {
				seen[id] = true
				out = append(out, id)
			}
		}
	}
	return out
}

// fieldIndex is the column each field is read from: the first column
// mapped to it, as in the existing upload. A level's column is the one
// named by its label or its canonical word.
func fieldIndex(headers []string, levels []Level) map[string]int {
	index := map[string]int{}
	levelOf := map[string]string{}
	for _, l := range levels {
		levelOf[normalizeHeader(l.Label)] = "level:" + l.ID
		levelOf[normalizeHeader(l.Canonical)] = "level:" + l.ID
		levelOf[strings.ReplaceAll(normalizeHeader(l.Canonical), " ", "")] = "level:" + l.ID
	}
	for i, h := range headers {
		key := normalizeHeader(h)
		field, ok := headerFields[key]
		if !ok {
			field, ok = levelOf[key]
		}
		if !ok {
			continue
		}
		if _, taken := index[field]; !taken {
			index[field] = i
		}
	}
	return index
}

// Preview says what each row of the sheet would come to in the country
// place holds. It reads nothing and writes nothing.
func Preview(s Sheet, place *Place) (Result, error) {
	index := fieldIndex(s.Headers, place.Levels)
	if _, ok := index["school_id"]; !ok {
		return Result{}, ErrFile("The file has no School ID column.")
	}
	if _, ok := index["name"]; !ok {
		return Result{}, ErrFile("The file has no School Name column.")
	}
	out := Result{Counts: map[string]int{Ready: 0, Existing: 0, Duplicate: 0, Rejected: 0, Skipped: 0}}
	taken := map[int]string{}
	for field, at := range index {
		taken[at] = field
	}
	for i, h := range s.Headers {
		c := Column{Header: h}
		switch field := taken[i]; {
		case strings.HasPrefix(field, "level:"):
			for _, l := range place.Levels {
				if "level:"+l.ID == field {
					c.TakenAs = l.Label
				}
			}
		default:
			c.TakenAs = field
		}
		out.Columns = append(out.Columns, c)
	}
	firstLine := map[string]int{}
	namesInFile := map[string]int{}
	nationalInFile := map[string]int{}
	for _, r := range s.Rows {
		cell := func(field string) string {
			at, ok := index[field]
			if !ok || at >= len(r.Cells) {
				return ""
			}
			return strings.TrimSpace(r.Cells[at])
		}
		res := RowResult{Line: r.Line, SchoolID: cell("school_id"), Name: cell("name"), NationalID: cell("national_id"),
			Units: []string{}, Messages: []string{}}
		blank := true
		for _, c := range r.Cells {
			if strings.TrimSpace(c) != "" {
				blank = false
				break
			}
		}
		if blank {
			res.Status = Skipped
			out.Counts[Skipped]++
			out.Rows = append(out.Rows, res)
			continue
		}
		rejected := false
		reject := func(m string) {
			rejected = true
			res.Messages = append(res.Messages, m)
		}
		if res.SchoolID == "" {
			reject("Missing School ID")
		}
		if res.Name == "" {
			reject("Missing School Name")
		}
		res.SchoolType = "client"
		if raw := cell("school_type"); raw != "" {
			if t, ok := schoolTypes[normalizeHeader(raw)]; ok {
				res.SchoolType = t
			} else {
				res.Messages = append(res.Messages, fmt.Sprintf("Current Partner Type '%s' was not recognised; Client is assumed", raw))
			}
		}
		units, problems, refused := place.locate(func(l Level) string {
			at, ok := index["level:"+l.ID]
			if !ok || at >= len(r.Cells) {
				return ""
			}
			return strings.TrimSpace(r.Cells[at])
		})
		res.Units = units
		res.Messages = append(res.Messages, problems...)
		rejected = rejected || refused
		if here, held := place.held[res.SchoolID]; held && !here {
			reject(fmt.Sprintf("School ID %s is held by a school of another country", res.SchoolID))
		}
		if res.NationalID != "" {
			if line, ok := nationalInFile[res.NationalID]; ok {
				res.Messages = append(res.Messages, fmt.Sprintf("National school ID %s is also on line %d", res.NationalID, line))
			} else {
				nationalInFile[res.NationalID] = r.Line
			}
		}
		switch line, repeated := firstLine[res.SchoolID]; {
		case rejected:
			res.Status = Rejected
		case repeated:
			res.Status = Duplicate
			res.Messages = append(res.Messages, fmt.Sprintf("School ID %s is already on line %d", res.SchoolID, line))
		case place.held[res.SchoolID]:
			res.Status = Existing
		default:
			res.Status = Ready
			if place.names[lookupKey(res.Name)] {
				res.Messages = append(res.Messages, "A school of the country already has this name; check it is not the same school")
			}
		}
		if res.SchoolID != "" && !rejected {
			if _, seen := firstLine[res.SchoolID]; !seen {
				firstLine[res.SchoolID] = r.Line
			}
		}
		if res.Status == Ready || res.Status == Existing {
			key := lookupKey(res.Name) + "\x00" + strings.Join(units, "\x00")
			if line, ok := namesInFile[key]; ok {
				res.Messages = append(res.Messages, fmt.Sprintf("Line %d has a school of the same name in the same place", line))
			} else {
				namesInFile[key] = r.Line
			}
		}
		out.Counts[res.Status]++
		out.Rows = append(out.Rows, res)
	}
	return out, nil
}

// locate places a row in the country's units, top level first. value gives
// the row's value for a level ("" when blank or not in the file). Each
// unit named must lie under the unit placed above it (any number of levels
// down, as a file may leave optional levels out). A required level that is
// missing or not found rejects the row; any other is a warning.
func (p *Place) locate(value func(Level) string) (units, messages []string, refused bool) {
	units, messages = []string{}, []string{}
	under := ""
	for _, l := range p.Levels {
		name := value(l)
		if name == "" {
			if l.Required {
				refused = true
				messages = append(messages, fmt.Sprintf("%s is required", l.Label))
			}
			continue
		}
		var matches []unit
		for _, u := range p.byName[l.ID][lookupKey(name)] {
			if under == "" || p.within(u, under) {
				matches = append(matches, u)
			}
		}
		switch len(matches) {
		case 1:
			under = matches[0].id
			units = append(units, matches[0].name)
		case 0:
			if l.Required {
				refused = true
			}
			if under == "" {
				messages = append(messages, fmt.Sprintf("%s '%s' was not found", l.Label, name))
			} else {
				messages = append(messages, fmt.Sprintf("%s '%s' was not found in %s", l.Label, name, p.byID[under].name))
			}
		default:
			if l.Required {
				refused = true
			}
			messages = append(messages, fmt.Sprintf("%s '%s' matches %d units; name the level above it too", l.Label, name, len(matches)))
		}
	}
	return units, messages, refused
}

// within says whether u lies under the unit with id ancestor.
func (p *Place) within(u unit, ancestor string) bool {
	for steps := 0; u.parentID != "" && steps < 12; steps++ {
		if u.parentID == ancestor {
			return true
		}
		u = p.byID[u.parentID]
	}
	return false
}

// Statuses are the statuses in the order a summary shows them.
func Statuses() []string { return []string{Ready, Existing, Duplicate, Rejected, Skipped} }
