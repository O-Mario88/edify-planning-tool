// Package catalogue is the Activity Catalogue settings page
// (/settings/activity-catalogue/, catalogue_views.activity_catalogue_page,
// pages/settings/activity_catalogue.html): the governed catalogue items under
// the page's filters, each with its use count, intervention, evidence, cost
// and Salesforce profiles, eligibility and version history; for a reader who
// manages the catalogue, every item whatever its state, the New activity
// button and the mapping corrections that wait on review. Each card is
// written as the template writes it and read by the feed's own rules
// (feeddom). Every save stays with the existing application.
//
// The rules are exported to rules.json by `manage.py
// export_activity_catalogue_rules`;
// apps/activity_catalogue/test_activity_catalogue_rules_export.py fails when
// the two differ.
package catalogue

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

// Path is the page.
const Path = "/settings/activity-catalogue/"

// reviewLimit is the review queue's [:100].
const reviewLimit = 100

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page, View, Manage bool
	} `json:"roles"`
	Statuses        [][2]string `json:"statuses"`
	ActivityTypes   [][2]string `json:"activity_types"`
	DeliveryMethods [][2]string `json:"delivery_methods"`
	Interventions   [][2]string `json:"interventions"`
	MappingModes    [][2]string `json:"mapping_modes"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Statuses) == 0 || len(r.Interventions) == 0 {
		panic(fmt.Sprintf("catalogue: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("catalogue: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

func label(choices [][2]string, value string) string {
	for _, c := range choices {
		if c[0] == value {
			return c[1]
		}
	}
	return value
}

func yesno(b bool) string {
	if b {
		return "Allowed"
	}
	return "Not allowed"
}

// orNone is the template's {{ value }} of a nullable column.
func orNone(s *string) string {
	if s == nil {
		return "None"
	}
	return *s
}

// Build answers Path; a reader without the catalogue's view permission is
// refused (403), and a request that opens the New activity drawer (?new=)
// is handed on.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role := rules.Roles[p.ActiveRole]
	if !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !role.View {
		return nil, true, pagegate.ErrForbidden
	}
	if query.Get("new") != "" {
		return nil, false, nil
	}
	resp, err := s.page(ctx, p, role.Manage, query)
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

type item struct {
	id, name, status, code, activityType, method, trainingCategory string
	training                                                       bool
	evidence, costing, salesforce, prefix                          *string
	staff, partner, school, cluster, project                       bool
	uses                                                           int
	mapping                                                        string
	versions                                                       []string
}

func (s *Service) page(ctx context.Context, p auth.Principal, manage bool, query url.Values) (*screensv1.GetPageResponse, error) {
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, fmt.Errorf("catalogue: resolving the reader's scope: %w", err)
	}
	projects, err := workplan.ScopedProjects(ctx, s.db, p, scope)
	if err != nil {
		return nil, err
	}
	items, err := s.items(ctx, manage, query, now)
	if err != nil {
		return nil, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Governed master data", Title: "Activity Catalogue"}
	if manage {
		header.Actions = []*screensv1.PageAction{{Key: "new_activity", Label: "New activity", Enabled: true,
			Href: "/settings/activity-catalogue/new", Drawer: true}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
		filter("intervention", "Intervention", "All interventions", rules.Interventions, query),
		filter("activity_type", "Activity type", "All types", rules.ActivityTypes, query),
		filter("delivery_method", "Delivery method", "All methods", rules.DeliveryMethods, query),
		filter("project_id", "Project", "All projects", projects, query),
		filter("status", "Status", "All statuses", rules.Statuses, query),
	}}}}}
	if manage {
		review, err := s.reviewBlock(ctx)
		if err != nil {
			return nil, err
		}
		blocks = append(blocks, review...)
	}
	el := feeddom.El
	for _, it := range items {
		blocks = feeddom.Walk(el("div", "", card(it, manage)), blocks)
	}
	if len(items) == 0 {
		blocks = feeddom.Walk(el("div", "", el("div", "card", "No Catalogue items match these filters.")), blocks)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}, nil
}

// filter is one of the filter bar's selects: its choices, the one asked for
// chosen when it is among them.
func filter(name, caption, blank string, choices [][2]string, query url.Values) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: caption, Options: []*screensv1.PageFilterOption{{Label: blank}}}
	for _, c := range choices {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: c[0], Label: c[1]})
		if c[0] == query.Get(name) {
			f.Value = c[0]
		}
	}
	return f
}

// items is list_catalogue under the filters (every item for a manager, the
// effective ones today for anyone else), by name and code, each with its
// count of live activities, its active mappings' interventions and its
// versions.
func (s *Service) items(ctx context.Context, manage bool, query url.Values, now time.Time) ([]item, error) {
	where, args := []string{"TRUE"}, []any{}
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	if !manage {
		local := now.In(zone)
		today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
		d := arg(today)
		where = append(where, "i.status = 'active'", "(i.effective_from IS NULL OR i.effective_from <= "+d+")",
			"(i.effective_to IS NULL OR i.effective_to >= "+d+")")
	}
	if v := query.Get("intervention"); v != "" {
		where = append(where, "EXISTS (SELECT 1 FROM activity_intervention_mapping m WHERE m.catalogue_item_id = i.id AND m.intervention = "+arg(v)+" AND m.active)")
	}
	if v := query.Get("activity_type"); v != "" {
		where = append(where, "i.activity_type = "+arg(v))
	}
	if v := query.Get("delivery_method"); v != "" {
		where = append(where, "i.delivery_method = "+arg(v))
	}
	if v := query.Get("status"); v != "" {
		where = append(where, "i.status = "+arg(v))
	}
	if v := query.Get("project_id"); v != "" {
		where = append(where, "EXISTS (SELECT 1 FROM activity_project_mapping pm WHERE pm.catalogue_item_id = i.id AND pm.project_id = "+arg(v)+" AND pm.active)")
	}
	rows, err := s.db.Query(ctx, `
SELECT i.id, i.display_name, i.status, i.stable_code, i.activity_type, i.delivery_method, COALESCE(i.training_category, ''), i.is_training_course,
  i.evidence_profile, i.costing_profile, i.salesforce_record_type, i.salesforce_expected_prefix,
  i.staff_delivery_allowed, i.partner_delivery_allowed, i.individual_school_allowed, i.cluster_delivery_allowed, i.project_delivery_allowed,
  (SELECT count(*) FROM activity a WHERE a.catalogue_item_id = i.id AND a.deleted_at IS NULL)
FROM activity_catalogue_item i WHERE `+strings.Join(where, " AND ")+` ORDER BY i.display_name, i.stable_code`, args...)
	if err != nil {
		return nil, fmt.Errorf("catalogue: reading the items: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (item, error) {
		var it item
		err := r.Scan(&it.id, &it.name, &it.status, &it.code, &it.activityType, &it.method, &it.trainingCategory, &it.training,
			&it.evidence, &it.costing, &it.salesforce, &it.prefix, &it.staff, &it.partner, &it.school, &it.cluster, &it.project, &it.uses)
		return it, err
	})
	if err != nil {
		return nil, fmt.Errorf("catalogue: reading the items: %w", err)
	}
	if len(items) == 0 {
		return items, nil
	}
	ids := make([]string, len(items))
	at := map[string]int{}
	for i, it := range items {
		ids[i] = it.id
		at[it.id] = i
	}
	// The mappings in their model order (priority, then the item's name),
	// each active one written as its intervention or, with none, its mode.
	rows, err = s.db.Query(ctx, `
SELECT m.catalogue_item_id, m.active, COALESCE(m.intervention, ''), m.mapping_mode
FROM activity_intervention_mapping m JOIN activity_catalogue_item ci ON ci.id = m.catalogue_item_id
WHERE m.catalogue_item_id = ANY($1) ORDER BY m.priority, ci.display_name`, ids)
	if err != nil {
		return nil, fmt.Errorf("catalogue: reading the mappings: %w", err)
	}
	for rows.Next() {
		var id, intervention, mode string
		var active bool
		if err := rows.Scan(&id, &active, &intervention, &mode); err != nil {
			rows.Close()
			return nil, fmt.Errorf("catalogue: reading the mappings: %w", err)
		}
		if !active {
			continue
		}
		shown := label(rules.Interventions, intervention)
		if intervention == "" {
			shown = label(rules.MappingModes, mode)
		}
		items[at[id]].mapping += shown
	}
	rows.Close()
	rows, err = s.db.Query(ctx, `
SELECT catalogue_item_id, version, COALESCE(change_reason, ''), created_at
FROM activity_catalogue_version WHERE catalogue_item_id = ANY($1) ORDER BY catalogue_item_id, version DESC`, ids)
	if err != nil {
		return nil, fmt.Errorf("catalogue: reading the versions: %w", err)
	}
	for rows.Next() {
		var id, reason string
		var version int
		var made time.Time
		if err := rows.Scan(&id, &version, &reason, &made); err != nil {
			rows.Close()
			return nil, fmt.Errorf("catalogue: reading the versions: %w", err)
		}
		items[at[id]].versions = append(items[at[id]].versions,
			"Version "+strconv.Itoa(version)+" · "+reason+" · "+made.In(zone).Format("2 Jan 2006 15:04"))
	}
	rows.Close()
	return items, rows.Err()
}

// card is one catalogue item's article as the template writes it.
func card(it item, manage bool) *feeddom.Node {
	el := feeddom.El
	line := it.code + " · " + label(rules.ActivityTypes, it.activityType) + " · " + label(rules.DeliveryMethods, it.method)
	if it.training {
		line += " · Training Catalogue"
		if it.trainingCategory != "" {
			line += " · " + it.trainingCategory
		}
	}
	uses := strconv.Itoa(it.uses) + " scheduled use"
	if it.uses != 1 {
		uses += "s"
	}
	side := el("div", "flex", el("span", "text-xs", uses))
	if manage && it.training {
		side.Add(" ", el("button", "btn h-8", "Edit training").Attr("type", "button",
			"hx-get", "/settings/activity-catalogue/"+it.id+"/edit", "hx-target", "#drawer-container", "hx-swap", "innerHTML"))
	}
	salesforce := orNone(it.salesforce)
	if it.prefix != nil && *it.prefix != "" {
		salesforce += " · " + *it.prefix
	}
	term := func(dt, dd string) *feeddom.Node {
		return el("div", "", el("dt", "text-xs", dt), el("dd", "", dd))
	}
	versions := el("ol", "list-decimal")
	for _, v := range it.versions {
		versions.Add(el("li", "", v))
	}
	details := el("details", "", el("summary", "", "Eligibility, history and lifecycle"), " ",
		el("p", "mt-2", "Staff: "+yesno(it.staff)+" · Partner: "+yesno(it.partner)+" · Individual School: "+yesno(it.school)+
			" · Cluster: "+yesno(it.cluster)+" · Project: "+yesno(it.project)), " ", versions)
	if manage {
		status := el("select", "").Attr("name", "status", "required", "required")
		for _, c := range rules.Statuses {
			status.Add(el("option", "", c[1]).Attr("value", c[0]))
		}
		details.Add(" ", el("form", "").Attr("method", "post", "action", "/settings/activity-catalogue/"+it.id+"/lifecycle").Add(
			el("label", "sr-only", "New status"), " ", status, " ", el("label", "sr-only", "Lifecycle reason"), " ",
			el("input", "").Attr("name", "reason", "required", "required", "maxlength", "1000"), " ",
			el("button", "btn btn-primary", "Save lifecycle").Attr("type", "submit")))
	}
	return el("article", "card", el("div", "flex",
		el("div", "", el("div", "flex", el("h2", "", it.name), " ", el("span", "pill", label(rules.Statuses, it.status))), " ",
			el("p", "mt-1 text-xs", line)),
		" ", side), " ",
		el("dl", "grid", term("Intervention", it.mapping), " ", term("Evidence", orNone(it.evidence)), " ",
			term("Cost profile", orNone(it.costing)), " ", term("Salesforce", salesforce)), " ", details)
}

// reviewBlock is the Catalogue Mapping Review card: the historical mappings
// that need a person's correction, oldest first (a hundred), read as its one
// form when it holds a single review.
func (s *Service) reviewBlock(ctx context.Context) ([]*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, review_kind, source_model, source_record_id, source_value, COALESCE(candidate_codes, '{}')
FROM activity_catalogue_review_queue WHERE status = 'needs_review' ORDER BY created_at LIMIT $1`, reviewLimit)
	if err != nil {
		return nil, fmt.Errorf("catalogue: reading the review queue: %w", err)
	}
	type review struct {
		id, kind, model, record, value string
		candidates                     []string
	}
	reviews, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (review, error) {
		var x review
		return x, r.Scan(&x.id, &x.kind, &x.model, &x.record, &x.value, &x.candidates)
	})
	if err != nil {
		return nil, fmt.Errorf("catalogue: reading the review queue: %w", err)
	}
	var options [][2]string
	if len(reviews) > 0 {
		rows, err := s.db.Query(ctx, `SELECT stable_code, display_name FROM activity_catalogue_item ORDER BY display_name`)
		if err != nil {
			return nil, fmt.Errorf("catalogue: reading the items to choose from: %w", err)
		}
		if options, err = pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
			var o [2]string
			return o, r.Scan(&o[0], &o[1])
		}); err != nil {
			return nil, fmt.Errorf("catalogue: reading the items to choose from: %w", err)
		}
	}
	el := feeddom.El
	list := el("div", "mt-3")
	for _, rv := range reviews {
		source := rv.value
		if source == "" {
			source = "(blank)"
		}
		line := "Source: " + source
		if len(rv.candidates) > 0 {
			line += " · Candidates: " + strings.Join(rv.candidates, ", ")
		}
		pick := el("select", "").Attr("name", "stable_code", "required", "required")
		pick.Add(el("option", "", "Choose the verified Catalogue item…").Attr("value", ""))
		for _, o := range options {
			pick.Add(el("option", "", o[0]+" · "+o[1]).Attr("value", o[0]))
		}
		form := el("form", "").Attr("method", "post", "action", "/settings/activity-catalogue/reviews/"+rv.id+"/resolve").Add(
			el("label", "sr-only", "Verified Catalogue item"), " ", pick, " ", el("label", "sr-only", "Correction rationale"), " ",
			el("input", "").Attr("name", "resolution_note", "required", "required", "maxlength", "1000",
				"placeholder", "Required correction rationale and source checked"), " ",
			el("button", "btn btn-primary", "Resolve").Attr("type", "submit"))
		list.Add(el("article", "rounded-control", el("p", "text-sm", rv.kind+" · "+rv.model+" #"+rv.record), " ",
			el("p", "mt-1 text-xs", line), " ", form), " ")
	}
	if len(reviews) == 0 {
		list.Add(el("p", "text-sm", "No ambiguous historical mappings await review."))
	}
	section := el("section", "card", el("div", "flex", el("div", "", el("p", "edify-page-eyebrow", "Manual correction"), " ",
		el("h2", "", "Catalogue Mapping Review")), " ", el("span", "pill", strconv.Itoa(len(reviews))+" open")), " ", list)
	if form := feeddom.CardForm(section); form != nil {
		rv := reviews[0]
		maxLength := int32(1000)
		pick := &screensv1.DrawerField{Name: "stable_code", Label: "Verified Catalogue item", Kind: "select", Required: true,
			Options: []*screensv1.DrawerOption{{Label: "Choose the verified Catalogue item…"}}}
		for _, o := range options {
			pick.Options = append(pick.Options, &screensv1.DrawerOption{Value: o[0], Label: o[0] + " · " + o[1]})
		}
		f := &screensv1.PageForm{Title: "Catalogue Mapping Review", Text: "Manual correction", SubmitLabel: "Resolve",
			Key: "/settings/activity-catalogue/reviews/" + rv.id + "/resolve",
			Items: []*screensv1.PageFormItem{
				{Kind: &screensv1.PageFormItem_Field{Field: pick}},
				{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{Name: "resolution_note", Label: "Correction rationale",
					Kind: "text", Required: true, MaxLength: &maxLength, Placeholder: "Required correction rationale and source checked"}}},
			}}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Form{Form: f}}}, nil
	}
	return feeddom.Walk(el("div", "", section), nil), nil
}
