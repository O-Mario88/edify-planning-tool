package partneroversight

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// ExportPath is Partner Monitoring's Export (oversight_views.
// partner_oversight_export_view): the page's items and the trainings
// Partners facilitate, as CSV or a workbook.
const ExportPath = "/partner-oversight/export"

const exportRefusal = "Your role does not include data export."

// exportHeader is partner_oversight_service.EXPORT_HEADER.
var exportHeader = []string{"Partner", "School ID", "School", "District", "District Type", "Cluster", "Managing CCEO",
	"Program Lead", "Support Type", "Training", "Purpose of Assignment", "Focus Intervention", "Stage", "Assigned On",
	"Scheduled For", "Activity Status", "Evidence", "Salesforce", "Payment", "Planned Cost (UGX)", "Next Action Owner",
	"Next Action", "Risks"}

// Export answers the export, or handled false for a query Go does not read.
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	role, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return "", nil, false, nil
	}
	if !role.Page {
		return "", nil, true, ErrNotAvailable
	}
	if !rbac.Grants(p.ActiveRole, "data.export") {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	if !drawn(p, role) {
		return "", nil, false, nil
	}
	// The format is the download's own: read before the page's query is.
	excel, csvAsked := wantsExcel(query), strings.EqualFold(strings.TrimSpace(query.Get("format")), "csv")
	query = passed(query)
	for key := range query {
		if contains(customPeriodKeys, key) {
			return "", nil, false, nil
		}
	}
	if strings.EqualFold(strings.TrimSpace(query.Get("period")), "custom") {
		return "", nil, false, nil
	}
	now := s.now()
	per, ok := readPeriod(query, now)
	if !ok {
		return "", nil, false, nil
	}
	kind := myplan.ReadExportKind(query)
	if kind == "online" {
		return "", nil, false, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	var staff, regions []string
	switch role.Lens {
	case "country", "region":
		if scope.Country == schooldirectory.NoCountry {
			return "", nil, false, nil
		}
		if role.Lens == "region" {
			regions = nonNil(scope.RegionIDs)
		}
	default:
		own, err := bothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
		if err != nil {
			return "", nil, true, err
		}
		staff = own
		if !role.OwnWorkOnly {
			if staff, err = bothIDSpaces(ctx, s.db, append(append([]string{}, own...), scope.SupervisedStaffIDs...)); err != nil {
				return "", nil, true, err
			}
		}
		if len(staff) == 0 {
			staff = []string{}
		}
	}
	items, trainings, err := s.exportedWork(ctx, p, query, per, staff, regions, kind, now)
	if err != nil {
		return "", nil, true, err
	}
	stem := "partner-oversight-" + per.fy
	if budgetSchoolList(kind) {
		ids := []string{}
		for _, i := range items {
			if i.activityID != "" {
				ids = append(ids, i.activityID)
			}
		}
		for _, t := range trainings {
			ids = append(ids, t.activityID)
		}
		sheets, ported, err := myplan.TableSheets(ctx, s.db, p.Country, ids, kind, now, false)
		if errors.Is(err, myplan.ErrUnported) || (err == nil && !ported) {
			return "", nil, false, nil
		}
		if err != nil {
			return "", nil, true, err
		}
		if csvAsked {
			body, err := workbook.FirstSheetCSV(sheets)
			return stem + ".csv", body, true, err
		}
		return workbookFile(stem, sheets)
	}
	rows, err := s.exportRows(ctx, items, trainings, dateOf(now.In(zone)))
	if err != nil {
		return "", nil, true, err
	}
	if excel {
		return workbookFile(stem, []workbook.Sheet{{Title: "Partner monitoring", Headers: exportHeader, Rows: rows}})
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	head := make([]workbook.Cell, len(exportHeader))
	for i, h := range exportHeader {
		head[i] = workbook.Text(h)
	}
	if err := w.Write(workbook.SafeCSVRow(head)); err != nil {
		return "", nil, true, err
	}
	for _, r := range rows {
		if err := w.Write(workbook.SafeCSVRow(r)); err != nil {
			return "", nil, true, err
		}
	}
	w.Flush()
	return stem + ".csv", buf.Bytes(), true, w.Error()
}

func workbookFile(stem string, sheets []workbook.Sheet) (string, []byte, bool, error) {
	var buf bytes.Buffer
	if err := workbook.Write(&buf, sheets); err != nil {
		return "", nil, true, err
	}
	return stem + ".xlsx", buf.Bytes(), true, nil
}

// wantsExcel is oversight_views._wants_excel: format=xlsx or excel.
func wantsExcel(q url.Values) bool {
	f := strings.ToLower(strings.TrimSpace(q.Get("format")))
	return f == "xlsx" || f == "excel"
}

// budgetSchoolList is export_kinds.SCHOOL_LISTS.
func budgetSchoolList(kind string) bool { return contains(rules.Export.SchoolLists, kind) }

// exportedWork is the view's items and trainings, narrowed as it narrows
// them.
func (s *Service) exportedWork(ctx context.Context, p auth.Principal, query url.Values, per period, staff, regions []string, kind string,
	now time.Time) ([]*item, []*training, error) {
	operational, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	years, err := schoolplanning.Horizon(ctx, s.db, p.Country, per.fy, operational, schooldirectory.FYOptions(now), now)
	if err != nil {
		return nil, nil, err
	}
	today := dateOf(now.In(zone))
	items, err := readItems(ctx, s.db, staff, regions, years, today)
	if err != nil {
		return nil, nil, err
	}
	items = narrow(items, per)
	trainings, err := readTrainings(ctx, s.db, staff, regions, years)
	if err != nil {
		return nil, nil, err
	}
	if err := annotate(ctx, s.db, items, today); err != nil {
		return nil, nil, err
	}
	partner := strings.TrimSpace(query.Get("partner"))
	if partner == "all" {
		partner = ""
	}
	lead := strings.TrimSpace(query.Get("program_lead"))
	if lead == rules.Export.Everyone {
		lead = ""
	}
	var wanted []string
	if lead != "" && lead != "unassigned" {
		if wanted, err = bothIDSpaces(ctx, s.db, []string{lead}); err != nil {
			return nil, nil, err
		}
	}
	leadKeeps := func(pl string) bool {
		switch lead {
		case "":
			return true
		case "unassigned":
			return pl == ""
		}
		return contains(wanted, pl)
	}
	activity := strings.TrimSpace(query.Get("activity_type"))
	if myplan.IsExportKind(activity) {
		activity = ""
	}
	status := strings.TrimSpace(query.Get("status"))
	if _, ok := rules.Export.StatusLabels[status]; ok {
		status = ""
	}
	member := query.Get("member")
	memberKeeps := func(cceo string) bool {
		return member == "" || member == "all" || first(cceo, "unassigned") == member
	}
	keptItems := []*item{}
	for _, i := range items {
		if (partner == "" || i.partnerID == partner) && leadKeeps(i.plID) && memberKeeps(i.cceoID) &&
			(activity == "" || i.activityType == activity) && (status == "" || i.deliveryPhase() == status) {
			keptItems = append(keptItems, i)
		}
	}
	keptTrainings := []*training{}
	for _, t := range trainings {
		if (partner == "" || t.partnerID == partner) && leadKeeps(t.plID) && memberKeeps(t.cceoID) &&
			(activity == "" || t.activityType == activity) && (status == "" || t.deliveryPhase() == status) {
			keptTrainings = append(keptTrainings, t)
		}
	}
	items, trainings = keptItems, keptTrainings
	asked := strings.ToLower(strings.TrimSpace(query.Get("status")))
	complete := func(i *item) bool {
		return i.deliveryPhase() == "completed" || in(rules.Work.Complete, i.activityStatus)
	}
	switch {
	case asked == "completed":
		items = filterItems(items, complete)
		trainings = filterTrainings(trainings, func(t *training) bool { return t.deliveryPhase() == "completed" })
	case asked == "scheduled":
		items = filterItems(items, func(i *item) bool { return !complete(i) })
		trainings = filterTrainings(trainings, func(t *training) bool { return t.deliveryPhase() != "completed" })
	case asked == "in_progress":
		items = filterItems(items, func(i *item) bool { return i.deliveryPhase() == asked })
		trainings = filterTrainings(trainings, func(t *training) bool { return t.deliveryPhase() == asked })
	}
	items = filterItems(items, func(i *item) bool { return myplan.KeepsKind(kind, i.activityType, false) })
	trainings = filterTrainings(trainings, func(t *training) bool { return myplan.KeepsKind(kind, t.activityType, false) })
	return items, trainings, nil
}

func filterItems(list []*item, keep func(*item) bool) []*item {
	out := []*item{}
	for _, i := range list {
		if keep(i) {
			out = append(out, i)
		}
	}
	return out
}

func filterTrainings(list []*training, keep func(*training) bool) []*training {
	out := []*training{}
	for _, t := range list {
		if keep(t) {
			out = append(out, t)
		}
	}
	return out
}

// exportRows is export_rows: each item, then each facilitated training.
func (s *Service) exportRows(ctx context.Context, items []*item, trainings []*training, today time.Time) ([][]workbook.Cell, error) {
	ids := []string{}
	for _, i := range items {
		if i.activityID != "" {
			ids = append(ids, i.activityID)
		}
	}
	for _, t := range trainings {
		ids = append(ids, t.activityID)
	}
	marks, err := myplan.DistrictTypeLabels(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	txt := workbook.Text
	day := func(t *time.Time) workbook.Cell {
		if t == nil {
			return txt("")
		}
		return txt(t.Format("2006-01-02"))
	}
	out := make([][]workbook.Cell, 0, len(items)+len(trainings))
	for _, i := range items {
		code := ""
		if i.schoolID != "" {
			code = i.schoolCode
		}
		// salesforce_status: set only from the activity behind the work.
		salesforce := ""
		switch {
		case i.activityID == "":
		case i.salesforceRecorded:
			salesforce = "recorded"
		default:
			salesforce = "missing"
		}
		cost := txt("")
		if i.plannedCost != nil {
			cost = workbook.Int(*i.plannedCost)
		}
		owner, action := nextAction(i)
		reasons := []string{}
		for _, r := range risksWithWords(i, today) {
			reasons = append(reasons, r.reason)
		}
		out = append(out, []workbook.Cell{txt(i.partnerName), txt(code), txt(i.schoolName), txt(i.district), txt(marks[i.activityID]),
			txt(i.clusterName), txt(i.cceoName), txt(i.plName), txt(i.supportType), txt(i.trainingName), txt(i.purposeLabel),
			txt(choiceLabel(i.targetIntervention, rules.Work.InterventionLabels)), txt(i.stage), day(i.assignmentDate),
			day(i.scheduledDate), txt(i.activityStatus), txt(i.evidenceStatus), txt(salesforce), txt(i.paymentStatus), cost,
			txt(owner), txt(action), txt(strings.Join(reasons, "; "))})
	}
	for _, t := range trainings {
		out = append(out, []workbook.Cell{txt(t.partnerName), txt(""), txt(""), txt(t.district), txt(marks[t.activityID]),
			txt(t.place), txt(t.cceoName), txt(t.plName), txt(rules.Export.FacilitatedSupportType), txt(t.name), txt(""), txt(t.intervention),
			txt(t.statusLabel(today)), txt(""), day(t.day), txt(t.status), txt(t.evidenceLabel), txt(t.salesforceID), txt(""),
			workbook.Int(t.fee), txt(""), txt(""), txt("")})
	}
	return out, nil
}
