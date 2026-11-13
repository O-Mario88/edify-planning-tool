package teamperformance

import "sort"

// The levels a reader breaks their total down by (breakdown.REGION …).
const (
	levelRegion   = "region"
	levelLead     = "lead"
	levelCCEO     = "cceo"
	levelDistrict = "district"
)

// column is breakdown.Column.
type column struct {
	key, label, sub string
	drill           [][2]string // the query that opens what is under it; nil at the bottom
	cells           map[string][2]*float64
}

type columnCell struct {
	label                 string
	target, achieved, pct *float64
}

func (c *column) cell(key string) columnCell {
	v := c.cells[key]
	return columnCell{label: c.label, target: v[0], achieved: v[1], pct: share(v[1], v[0])}
}

// breakdown is breakdown.Breakdown.
type breakdown struct {
	level            string
	levels           []string
	columns          []*column
	inRegion, inLead string
	inLeadLabel      string
}

func (b *breakdown) label() string { return rules.BreakdownLabels[b.level] }

func (b *breakdown) narrowedTo() string {
	if b.inLeadLabel != "" {
		return b.inLeadLabel
	}
	return b.inRegion
}

func (b *breakdown) below() string {
	for i, l := range b.levels {
		if l == b.level && i+1 < len(b.levels) {
			return b.levels[i+1]
		}
	}
	return ""
}

func (b *breakdown) bars(key string) []bar {
	rows := []bar{}
	for _, c := range b.columns {
		v := c.cells[key]
		rows = append(rows, bar{label: c.label, target: v[0], achieved: v[1]})
	}
	return bars(rows)
}

func levelsOf(ro *roster) []string {
	if ro.own() {
		return []string{levelDistrict}
	}
	if ro.narrowed() {
		return []string{levelCCEO}
	}
	return []string{levelRegion, levelLead, levelCCEO}
}

func contains(values []string, v string) bool {
	for _, x := range values {
		if x == v {
			return true
		}
	}
	return false
}

// resolve is breakdown.resolve: the level asked for, narrowed as asked;
// anything the reader may not ask for falls back to their top level.
func (r *report) resolve(by, inRegion, inLead string) *breakdown {
	allowed := levelsOf(r.roster)
	level := allowed[0]
	if contains(allowed, by) {
		level = by
	}
	narrowable := len(allowed) > 1
	if !(narrowable && level == levelCCEO && r.roster.team(inLead) != nil) {
		inLead = ""
	}
	if !(narrowable && inLead == "" && (level == levelLead || level == levelCCEO) && contains(r.ledger.regions, inRegion)) {
		inRegion = ""
	}
	key := [3]string{level, inRegion, inLead}
	if b, ok := r.breakdowns[key]; ok {
		return b
	}
	b := &breakdown{level: level, levels: allowed, columns: r.columnsOf(level, inRegion, inLead), inRegion: inRegion, inLead: inLead}
	if inLead != "" {
		b.inLeadLabel = r.roster.team(inLead).label
	}
	r.breakdowns[key] = b
	return b
}

func (r *report) under(b *breakdown) *breakdown {
	level := b.below()
	if level == "" {
		return nil
	}
	return r.resolve(level, b.inRegion, b.inLead)
}

func (r *report) columnsOf(level, inRegion, inLead string) []*column {
	if level == levelRegion || level == levelDistrict {
		return r.placeColumns(level)
	}
	out := []*column{}
	if level == levelLead {
		for _, t := range r.roster.teams {
			if inRegion != "" && !worksIn(t)[inRegion] {
				continue
			}
			out = append(out, r.figuresColumn(t.key, t.label, r.teamScope(t), t.place, [][2]string{{"by", levelCCEO}, {"in_lead", t.key}}))
		}
		return out
	}
	leadership := len(levelsOf(r.roster)) > 1
	for _, t := range r.roster.teams {
		if inLead != "" && t.key != inLead {
			continue
		}
		for _, o := range t.officers {
			if inRegion != "" && o.region != inRegion {
				continue
			}
			sub := o.region
			if leadership {
				sub = t.label
			}
			out = append(out, r.figuresColumn(o.staffID, o.name, officerScope(o.staffID), sub, nil))
		}
	}
	return out
}

func worksIn(t *team) map[string]bool {
	out := map[string]bool{}
	if t.place != "" {
		out[t.place] = true
	}
	for _, o := range t.officers {
		if o.region != "" {
			out[o.region] = true
		}
	}
	return out
}

func (r *report) figuresColumn(key, label string, s scope, sub string, drill [][2]string) *column {
	f := r.summaryFigures(s, r.period.toDate())
	c := &column{key: key, label: label, sub: sub, drill: drill, cells: map[string][2]*float64{}}
	for _, m := range r.areas() {
		c.cells[m.Key] = [2]*float64{f[m.Key+"_target"], f[m.Key]}
	}
	return c
}

func (r *report) placeColumns(level string) []*column {
	columns := map[string]*column{}
	order := []string{}
	for _, m := range r.areas() {
		places, tgt, ach := r.placeSplit(m.Key, level)
		for _, place := range places {
			c := columns[place]
			if c == nil {
				var drill [][2]string
				if level == levelRegion && place != rules.NotPlaced {
					drill = [][2]string{{"by", levelLead}, {"in_region", place}}
				}
				c = &column{key: place, label: place, drill: drill, cells: map[string][2]*float64{}}
				columns[place] = c
				order = append(order, place)
			}
			c.cells[m.Key] = [2]*float64{ptr(float64(tgt.n[place])), ptr(float64(ach.n[place]))}
		}
	}
	out := []*column{}
	for _, place := range order {
		out = append(out, columns[place])
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].key != rules.NotPlaced && out[j].key == rules.NotPlaced })
	return out
}
