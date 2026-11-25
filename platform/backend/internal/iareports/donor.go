package iareports

// The donor version (donor_drawer, donor_request → request_donor_release;
// release_drawer, release_decide → decide_donor_release): the reviewer or
// the Country Director asks for it, and a Regional Vice President covering
// the country who neither wrote, reviewed nor asked for it approves or
// declines it.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaredaction"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	eventDonorRequested = "ia.report.donor_approval_requested"
	eventDonorDecided   = "ia.report.donor_decided"
	roleRVP             = "RegionalVicePresident"
)

var releaseStatusLabels = map[string]string{"pending_approval": "Awaiting approval", "approved": "Approved", "released": "Released", "revoked": "Revoked"}

// countText is the view's _count.
func countText(v any) string {
	if v == suppressed {
		return "Suppressed (fewer than 5)"
	}
	if v == nil || v == "" {
		return "0"
	}
	return str(v)
}

// shareText is the view's _share.
func shareText(v any) string {
	if v == nil {
		return "Not measured"
	}
	if v == suppressed {
		return "Suppressed (fewer than 5 schools)"
	}
	return str(v) + "%"
}

// donorFacts is the view's _donor_facts.
func donorFacts(payload map[string]any) []*screensv1.PageFact {
	cohort, portfolio, narrative := object(payload["cohort"]), object(payload["portfolio"]), object(payload["narrative"])
	change := "Not measured"
	if len(portfolio) > 0 {
		change = fmt.Sprintf("%s of %s schools measured · improved %s · %s", countText(portfolio["measured"]),
			countText(portfolio["schools_in_scope"]), shareText(portfolio["improved_pct"]), str(getOr(portfolio, "evidence", "")))
	}
	return []*screensv1.PageFact{
		{Label: "Project cohort", Value: fmt.Sprintf("%s measured of %s enrolments · improved %s · declined %s",
			countText(cohort["measured"]), countText(cohort["enrolments"]), shareText(cohort["improved_pct"]), shareText(cohort["declined_pct"]))},
		{Label: "School change", Value: orDash(change)},
		{Label: "Findings (as donors read them)", Value: orDash(str(narrative["findings"]))},
		{Label: "Limitations", Value: orDash(str(narrative["limitations"]))},
		{Label: "Suppressed cells", Value: str(getOr(payload, "suppressed_cells", json.Number("0")))},
	}
}

// donorPreview is redact(snapshot_with_people(report), DONOR, …).
func (r Reports) donorPreview(ctx context.Context, q pgxQuerier, x *report) (map[string]any, error) {
	snapshot, _, err := storedSnapshot(ctx, q, x.id)
	if err != nil {
		return nil, err
	}
	if err := r.withPeople(ctx, q, x.id, snapshot); err != nil {
		return nil, err
	}
	recs, err := recommendationPayloadFrom(ctx, q, x.id)
	if err != nil {
		return nil, err
	}
	payload := iaredaction.DonorPayload(snapshot, map[string]string{"methodology": x.methodology, "findings": x.findings, "limitations": x.limitations}, recs)
	// Round-trip as JSONField stores it, so the counts read back as numbers.
	b, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	d := json.NewDecoder(strings.NewReader(string(b)))
	d.UseNumber()
	var out map[string]any
	return out, d.Decode(&out)
}

type pgxQuerier = schooldirectory.Querier

// donorDrawer is donor_drawer.
func (r Reports) donorDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	x, err := r.visible(ctx, r.DB, p, id, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	may, err := r.mayReleaseSchools(ctx, r.DB, p, x)
	if err != nil {
		return nil, err
	}
	if !may {
		return emptyDrawer("Request the donor version", x.title,
			"The report's reviewer or the Country Director requests the donor version, after the leadership release."), nil
	}
	preview, err := r.donorPreview(ctx, r.DB, x)
	if err != nil {
		return nil, err
	}
	return &screensv1.PageDrawer{Title: "Request the donor version", Subtitle: x.title, HasRequired: true,
		SubmitLabel: "Request RVP approval", CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: donorFacts(preview)}}},
			note("Donors receive aggregates only; any figure resting on fewer than five schools is suppressed."),
			field(&screensv1.DrawerField{Name: "note", Label: "Note to the approving RVP", Kind: "textarea", MaxLength: proto.Int32(2000)}),
		}}, nil
}

// requestDonor is reports.request_donor_release.
func (r Reports) requestDonor(ctx context.Context, p auth.Principal, id, words string) (Saved, error) {
	now := r.now()
	var x *report
	var reviewer string
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.visible(ctx, tx, p, id, true); err != nil {
			return err
		}
		if x == nil {
			return refuse("That impact report is not in your country.")
		}
		if x.status != "released" {
			return refuse("A donor version follows the leadership release; release the report first.")
		}
		may, err := r.mayReleaseSchools(ctx, tx, p, x)
		if err != nil {
			return err
		}
		if !may {
			return refuse("The report's reviewer or the Country Director requests the donor version.")
		}
		var existing, status string
		err = tx.QueryRow(ctx, `SELECT id, status FROM impact_report_release WHERE report_id = $1 AND audience = 'donor' AND school_id IS NULL
FOR UPDATE`, id).Scan(&existing, &status)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("iareports: the donor version: %w", err)
		}
		if existing != "" && status != "revoked" {
			return refuse("The donor version is already %s.", lower(releaseStatusLabels[status]))
		}
		payload, err := r.donorPreview(ctx, tx, x)
		if err != nil {
			return err
		}
		stored, _ := json.Marshal(payload)
		release := existing
		if existing == "" {
			release = cuid.New()
			_, err = tx.Exec(ctx, `INSERT INTO impact_report_release (id, created_at, updated_at, audience, redaction_profile, rendered_payload,
  status, requested_by_id, approved_by_id, approved_at, released_by_id, released_at, revoked_reason, report_id, school_id)
VALUES ($1, $2, $2, 'donor', 'donor', $3::jsonb, 'pending_approval', $4, NULL, NULL, NULL, NULL, '', $5, NULL)`, release, now, string(stored), p.UserID, id)
		} else {
			_, err = tx.Exec(ctx, `UPDATE impact_report_release SET redaction_profile = 'donor', rendered_payload = $2::jsonb,
  status = 'pending_approval', requested_by_id = $3, approved_by_id = NULL, approved_at = NULL, released_by_id = NULL, released_at = NULL,
  revoked_reason = '', updated_at = $4 WHERE id = $1`, release, string(stored), p.UserID, now)
		}
		if err != nil {
			return fmt.Errorf("iareports: requesting the donor version: %w", err)
		}
		var hash string
		_ = tx.QueryRow(ctx, `SELECT snapshot_hash, COALESCE(reviewed_by_id, '') FROM impact_report WHERE id = $1`, id).Scan(&hash, &reviewer)
		var noted any
		e := reportAudit("ia.report.donor_requested", id, p, x.country, x.version, x.status, hash, map[string]any{"release_id": release, "note": nil})
		if words != "" {
			noted = words
			e.Payload.(map[string]any)["note"] = noted
			reason := words
			if len([]rune(reason)) > 500 {
				reason = string([]rune(reason)[:500])
			}
			e.Reason = &reason
		}
		_, err = audit.Append(ctx, tx, e, now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	covering, err := r.rvpsCovering(ctx, x.country, map[string]bool{x.author: true, reviewer: true, p.UserID: true})
	if err != nil && r.Logger != nil {
		r.Logger.Warn("iareports: the approving RVPs were not found", "report", x.id, "err", err)
	}
	body := words
	if body == "" {
		body = x.country + " · " + iapages.PeriodLabel(x.fy, x.start, x.end)
	}
	r.tell(ctx, x, eventDonorRequested, "Donor version to approve: "+x.title, body, "high", covering, "#releases", "Review Donor Version")
	return Saved{Message: "Donor version requested; an RVP approves it.", ReportID: id}, nil
}

// tell is reports._notify for an ImpactReport notice.
func (r Reports) tell(ctx context.Context, x *report, event, title, body, priority string, to []string, anchor, label string) {
	seen := map[string]bool{}
	recipients := []activities.NoticeTo{}
	for _, id := range to {
		if id == "" || seen[id] {
			continue
		}
		seen[id] = true
		recipients = append(recipients, activities.NoticeTo{UserID: id, Route: PagePath + x.id + "/" + anchor, Label: label})
	}
	if len(recipients) == 0 {
		return
	}
	if len([]rune(title)) > 200 {
		title = string([]rune(title)[:200])
	}
	if len([]rune(body)) > 500 {
		body = string([]rune(body)[:500])
	}
	if err := activities.SendNotices(ctx, r.DB, r.Push, r.Live, r.Logger, r.now(), x.id, "", activities.Origin{},
		activities.Notice{Title: title, Body: body, Event: event, Category: "ia", ContextType: "ImpactReport", Priority: priority},
		recipients); err != nil && r.Logger != nil {
		r.Logger.Warn("iareports: a notice was not sent", "report", x.id, "event", event, "err", err)
	}
}

// rvpsCovering is _rvps_covering over role_recipients(RVP), less the people
// in skip.
func (r Reports) rvpsCovering(ctx context.Context, country string, skip map[string]bool) ([]string, error) {
	rows, err := r.DB.Query(ctx, `SELECT id FROM "user" WHERE 'RegionalVicePresident' = ANY(roles) AND is_active AND deleted_at IS NULL ORDER BY id`)
	if err != nil {
		return nil, fmt.Errorf("iareports: the RVPs: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	out := []string{}
	for _, id := range ids {
		if skip[id] {
			continue
		}
		covers, err := r.rvpCovers(ctx, r.DB, auth.Principal{Account: auth.Account{UserID: id, ActiveRole: roleRVP, Roles: []string{roleRVP}}}, country)
		if err != nil {
			return nil, err
		}
		if covers {
			out = append(out, id)
		}
	}
	return out, nil
}

// rvpCovers is _rvp_covers: an RVP with no region on file covers every
// country.
func (r Reports) rvpCovers(ctx context.Context, q schooldirectory.Querier, p auth.Principal, country string) (bool, error) {
	if p.ActiveRole != roleRVP {
		return false, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, q, p, r.now())
	if err != nil {
		return false, err
	}
	if !scope.RegionScope {
		return true, nil
	}
	var covers bool
	ids := scope.RegionIDs
	if ids == nil {
		ids = []string{}
	}
	err = q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM region WHERE id = ANY($1) AND country = $2)`, ids, country).Scan(&covers)
	return covers, err
}

// donorReleaseDrawer is release_drawer for the donor version.
func (r Reports) donorReleaseDrawer(ctx context.Context, p auth.Principal, x *report, id, label string) (*screensv1.PageDrawer, bool, error) {
	var raw []byte
	var status, revoked, requested string
	if err := r.DB.QueryRow(ctx, `SELECT rendered_payload::text, status, revoked_reason, requested_by_id FROM impact_report_release WHERE id = $1`, id).
		Scan(&raw, &status, &revoked, &requested); err != nil {
		return nil, true, fmt.Errorf("iareports: the donor version: %w", err)
	}
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	var payload map[string]any
	if err := d.Decode(&payload); err != nil {
		return nil, true, fmt.Errorf("iareports: reading the donor version: %w", err)
	}
	facts := donorFacts(payload)
	if revoked != "" {
		facts = append(facts, &screensv1.PageFact{Label: "Declined because", Value: revoked})
	}
	var reviewer string
	_ = r.DB.QueryRow(ctx, `SELECT COALESCE(reviewed_by_id, '') FROM impact_report WHERE id = $1`, x.id).Scan(&reviewer)
	covers, err := r.rvpCovers(ctx, r.DB, p, x.country)
	if err != nil {
		return nil, true, err
	}
	subtitle := "Donors · " + label
	factItem := &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}}
	me := p.UserID
	if covers && status == "pending_approval" && me != "" && me != x.author && me != reviewer && me != requested {
		return &screensv1.PageDrawer{Title: "Approve the donor version", Subtitle: subtitle, HasRequired: true, SubmitLabel: "Save decision",
			CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{factItem,
				note("Check that nothing in the words names a school or a person before approving."),
				field(&screensv1.DrawerField{Name: "decision", Label: "Decision", Kind: "select", Required: true, Value: "approve",
					Options: []*screensv1.DrawerOption{{Value: "approve", Label: "Approve and release to donors"}, {Value: "decline", Label: "Decline (say why)"}}}),
				field(&screensv1.DrawerField{Name: "note", Label: "Note", Kind: "textarea", MaxLength: proto.Int32(2000)}),
			}}, true, nil
	}
	return &screensv1.PageDrawer{Title: "Donor version", Subtitle: subtitle, HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{factItem, note("Read only.")}}, true, nil
}

// decideDonor is reports.decide_donor_release.
func (r Reports) decideDonor(ctx context.Context, p auth.Principal, reportID, id string, values map[string]string) (Saved, error) {
	decision := values["decision"]
	if decision != "approve" && decision != "decline" {
		return Saved{}, refuse("Choose approve or decline.")
	}
	words := strings.TrimSpace(values["note"])
	if decision == "decline" && words == "" {
		return Saved{}, refuse("Say why the donor version is declined.")
	}
	if p.ActiveRole != roleRVP {
		return Saved{}, refuse("A Regional Vice President approves donor versions.")
	}
	now := r.now()
	var x *report
	var requested string
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.visible(ctx, tx, p, reportID, false); err != nil {
			return err
		}
		var status string
		if x != nil {
			err = tx.QueryRow(ctx, `SELECT status, requested_by_id FROM impact_report_release WHERE id = $1 AND report_id = $2 AND audience = 'donor'
FOR UPDATE`, id, reportID).Scan(&status, &requested)
			if errors.Is(err, pgx.ErrNoRows) {
				x = nil
			} else if err != nil {
				return fmt.Errorf("iareports: the donor version: %w", err)
			}
		}
		if x == nil {
			return refuse("That donor version is not in your region.")
		}
		covers, err := r.rvpCovers(ctx, tx, p, x.country)
		if err != nil {
			return err
		}
		if !covers {
			return refuse("That donor version is not in your region.")
		}
		if status != "pending_approval" {
			return refuse("This donor version is %s, not awaiting approval.", lower(releaseStatusLabels[status]))
		}
		var reviewer, hash string
		_ = tx.QueryRow(ctx, `SELECT COALESCE(reviewed_by_id, ''), snapshot_hash FROM impact_report WHERE id = $1`, reportID).Scan(&reviewer, &hash)
		if p.UserID == x.author || p.UserID == reviewer || p.UserID == requested {
			return refuse("The donor version is approved by someone who did not write, review or request it.")
		}
		action := "ia.report.donor_released"
		if decision == "approve" {
			_, err = tx.Exec(ctx, `UPDATE impact_report_release SET status = 'released', approved_by_id = $2, approved_at = $3, released_by_id = $2,
  released_at = $3, updated_at = $3 WHERE id = $1`, id, p.UserID, now)
		} else {
			action = "ia.report.donor_declined"
			kept := words
			if len([]rune(kept)) > 4000 {
				kept = string([]rune(kept)[:4000])
			}
			_, err = tx.Exec(ctx, `UPDATE impact_report_release SET status = 'revoked', revoked_reason = $2, updated_at = $3 WHERE id = $1`, id, kept, now)
		}
		if err != nil {
			return fmt.Errorf("iareports: deciding the donor version: %w", err)
		}
		e := reportAudit(action, reportID, p, x.country, x.version, x.status, hash, map[string]any{"release_id": id, "note": nil})
		if words != "" {
			e.Payload.(map[string]any)["note"] = words
			reason := words
			if len([]rune(reason)) > 500 {
				reason = string([]rune(reason)[:500])
			}
			e.Reason = &reason
		}
		if _, err := audit.Append(ctx, tx, e, now); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'ImpactReport', $2, $3)`, eventDonorRequested, reportID, now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	title, priority, message := "Donor version released: "+x.title, "normal", "Donor version approved and released."
	if decision == "decline" {
		title, priority, message = "Donor version declined: "+x.title, "high", "Donor version declined."
	}
	body := words
	if body == "" {
		body = iapages.PeriodLabel(x.fy, x.start, x.end)
	}
	r.tell(ctx, x, eventDonorDecided, title, body, priority, []string{requested, x.author}, "#releases", "Open Report")
	return Saved{Message: message, ReportID: reportID}, nil
}

// recommendationPayloadFrom is recommendation_payload over any querier.
func recommendationPayloadFrom(ctx context.Context, q schooldirectory.Querier, id string) ([]map[string]any, error) {
	rows, err := q.Query(ctx, `SELECT id, text, owner_role, COALESCE(to_char(due_date, 'YYYY-MM-DD'), '') FROM impact_report_recommendation
WHERE report_id = $1 ORDER BY due_date, created_at`, id)
	if err != nil {
		return nil, fmt.Errorf("iareports: the recommendations: %w", err)
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var rid, text, owner, due string
		if err := rows.Scan(&rid, &text, &owner, &due); err != nil {
			return nil, fmt.Errorf("iareports: a recommendation: %w", err)
		}
		out = append(out, map[string]any{"id": rid, "text": text, "owner_role": owner, "owner_label": ownerLabel(owner), "due_date": due})
	}
	return out, rows.Err()
}
