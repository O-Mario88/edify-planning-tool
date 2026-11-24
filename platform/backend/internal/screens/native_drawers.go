package screens

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fieldops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ── Native GetMyPlan (delegates to registered Go /my-plan page builder) ──────

func (s *Service) getMyPlanInGo(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetMyPlanResponse, bool, error) {
	for _, builder := range s.pages {
		page, served, err := builder.Build(ctx, p, "/my-plan", query)
		if err != nil {
			return nil, true, err
		}
		if served && page != nil {
			return &screensv1.GetMyPlanResponse{
				Header:  page.GetHeader(),
				Tabs:    page.GetTabs(),
				Blocks:  page.GetBlocks(),
				WebPath: "/my-plan",
			}, true, nil
		}
	}
	return nil, false, nil
}

// ── Native PlanningDrawer GET, Assign SAVE, and GetTrainingCapacity ──────────

func (s *Service) getPlanningDrawerInGo(ctx context.Context, p auth.Principal, schoolID, kind string) (*screensv1.GetPlanningDrawerResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if kind == "schedule" {
		return s.getScheduleDrawerInGo(ctx, p, schoolID)
	}
	if kind == "assign" {
		return s.getAssignDrawerInGo(ctx, p, schoolID)
	}
	// No other kind exists.
	return nil, false, nil
}

func (s *Service) getTrainingCapacityInGo(ctx context.Context, p auth.Principal, req *screensv1.GetTrainingCapacityRequest) (*screensv1.GetTrainingCapacityResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	now := s.clock()
	if d, err := time.Parse(time.DateOnly, strings.TrimSpace(req.GetDate())); err == nil {
		now = d
	}
	fyYear := now.Year()
	if now.Month() >= time.October {
		fyYear++
	}
	fy := fmt.Sprintf("FY%d", fyYear)

	var scheduled int32
	var counted bool
	staffID := p.StaffProfileID
	if staffID == "" {
		staffID = p.UserID
	}
	_ = s.db.QueryRow(ctx, `
SELECT COUNT(*)::int
  FROM activity
 WHERE deleted_at IS NULL
   AND fy = $1
   AND responsible_staff_id = $2
   AND status NOT IN ('cancelled')
   AND (training_course_id = $3 OR $3 = '')`, fy, staffID, req.GetTraining()).Scan(&scheduled)

	if req.GetSchool() != "" {
		_ = s.db.QueryRow(ctx, `
SELECT EXISTS(
  SELECT 1 FROM activity
   WHERE deleted_at IS NULL
     AND fy = $1
     AND school_id = $2
     AND status NOT IN ('cancelled')
     AND (training_course_id = $3 OR $3 = '')
)`, fy, req.GetSchool(), req.GetTraining()).Scan(&counted)
	}

	return &screensv1.GetTrainingCapacityResponse{
		Managed:   false,
		Scheduled: scheduled,
		StaffName: p.Name,
		Fy:        fy,
		Counted:   counted,
	}, true, nil
}

// ── Native GetDrawerOptions ──────────────────────────────────────────────────

func (s *Service) getDrawerOptionsInGo(ctx context.Context, source, name, value string) (*screensv1.GetDrawerOptionsResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	var opts []*screensv1.DrawerOption
	switch {
	case strings.Contains(source, "sub-count") || name == "district" || name == "district_id":
		rows, err := s.db.Query(ctx, `
SELECT id, name FROM cluster
 WHERE deleted_at IS NULL AND ($1 = '' OR district_id = $1)
 ORDER BY name ASC LIMIT 200`, value)
		if err == nil {
			for rows.Next() {
				var id, label string
				if rows.Scan(&id, &label) == nil {
					opts = append(opts, &screensv1.DrawerOption{Value: id, Label: label})
				}
			}
			rows.Close()
		}
	case strings.Contains(source, "school") || name == "cluster" || name == "cluster_id":
		rows, err := s.db.Query(ctx, `
SELECT id, name, COALESCE(school_id, '') FROM school
 WHERE deleted_at IS NULL AND ($1 = '' OR cluster_id = $1)
 ORDER BY name ASC LIMIT 200`, value)
		if err == nil {
			for rows.Next() {
				var id, label, code string
				if rows.Scan(&id, &label, &code) == nil {
					opts = append(opts, &screensv1.DrawerOption{Value: id, Label: label, Detail: code})
				}
			}
			rows.Close()
		}
	default:
		rows, err := s.db.Query(ctx, `
SELECT id, name FROM training_course
 WHERE deleted_at IS NULL ORDER BY name ASC LIMIT 100`)
		if err == nil {
			for rows.Next() {
				var id, label string
				if rows.Scan(&id, &label) == nil {
					opts = append(opts, &screensv1.DrawerOption{Value: id, Label: label})
				}
			}
			rows.Close()
		}
	}
	return &screensv1.GetDrawerOptionsResponse{Options: opts}, true, nil
}

// ── Native School Drawers (GetSchoolDrawer & SaveSchoolDrawer) ───────────────

func (s *Service) getSchoolDrawerInGo(ctx context.Context, p auth.Principal, schoolID, kind string) (*screensv1.GetSchoolDrawerResponse, bool, error) {
	// Only the drawers Go has a form for: Close School is not one, and must
	// not open the edit form.
	if !s.nativeForms() || !nativeSchoolDrawer(kind) {
		return nil, false, nil
	}
	var sID, sCode, name, phone, contact, contactPhone, addr, head, dir string
	var enrollment int
	err := s.db.QueryRow(ctx, `
SELECT id, COALESCE(school_id, ''), name, COALESCE(school_phone, ''),
       COALESCE(primary_contact_name, ''), COALESCE(primary_contact_phone, ''),
       COALESCE(enrollment, 0), COALESCE(shipping_address, ''),
       COALESCE(headteacher_name, ''), COALESCE(director_name, '')
  FROM school
 WHERE (id = $1 OR school_id = $1) AND deleted_at IS NULL
 LIMIT 1`, schoolID).Scan(&sID, &sCode, &name, &phone, &contact, &contactPhone, &enrollment, &addr, &head, &dir)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "School not found.")
	}
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}

	if inReach, err := s.schoolsInReach(ctx, p, sID); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "School not found.")
	}

	if isSSADrawer(kind) {
		year := fieldItem("fy", "Fiscal Year", "text", schooldirectory.OperationalFY(s.clock()), true)
		year.GetField().ReadOnly = true
		items := []*screensv1.DrawerItem{
			year,
			fieldItem("quarter", "Quarter", "select", "Q1", true, "Q1", "Q2", "Q3", "Q4"),
			fieldItem("new_enrollment", "Current Enrollment", "number", strconv.Itoa(enrollment), false),
		}
		for _, iv := range fieldops.SSAInterventions {
			items = append(items, fieldItem("score_"+iv.Key, iv.Label+" (0–10)", "number", "", true))
		}
		return &screensv1.GetSchoolDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Record SSA Scores",
				Subtitle:    fmt.Sprintf("%s · %s", sCode, name),
				HasRequired: true,
				SubmitLabel: "Save SSA",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items:       items,
			},
		}, true, nil
	}

	return &screensv1.GetSchoolDrawerResponse{
		Drawer: &screensv1.PageDrawer{
			Title:       "Edit School Details",
			Subtitle:    fmt.Sprintf("%s · %s", sCode, name),
			HasRequired: true,
			SubmitLabel: "Save changes",
			CancelLabel: "Cancel",
			CanSubmit:   canMutateSchoolAssignment(p.ActiveRole),
			Items: []*screensv1.DrawerItem{
				fieldItem("name", "School Name", "text", name, true),
				fieldItem("school_phone", "School Phone", "tel", phone, false),
				fieldItem("primary_contact_name", "Primary Contact", "text", contact, false),
				fieldItem("primary_contact_phone", "Contact Phone", "tel", contactPhone, false),
				fieldItem("enrollment", "Enrollment", "number", strconv.Itoa(enrollment), false),
				fieldItem("shipping_address", "Address", "text", addr, false),
				fieldItem("headteacher_name", "Headteacher", "text", head, false),
				fieldItem("director_name", "Director", "text", dir, false),
			},
		},
	}, true, nil
}

func (s *Service) saveSchoolDrawerInGo(ctx context.Context, p auth.Principal, req *screensv1.SaveSchoolDrawerRequest) (*screensv1.SaveSchoolDrawerResponse, bool, error) {
	if !s.nativeForms() || !nativeSchoolDrawer(req.GetKind()) {
		return nil, false, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, req.GetSchoolId()); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.SaveSchoolDrawerResponse{Saved: false, Error: "This school is outside your portfolio."}, true, nil
	}
	vals := req.GetValues()
	if isSSADrawer(req.GetKind()) && s.fieldOps != nil {
		var scores []fieldops.SSAScoreInput
		for k, v := range vals {
			if strings.HasPrefix(k, "score_") {
				if parsed, err := strconv.ParseFloat(strings.TrimSpace(v), 64); err == nil {
					scores = append(scores, fieldops.SSAScoreInput{
						Intervention: strings.TrimPrefix(k, "score_"),
						Score:        parsed,
					})
				}
			}
		}
		enr, _ := strconv.Atoi(strings.TrimSpace(vals["new_enrollment"]))
		fy := strings.TrimSpace(vals["fy"])
		if fy == "" {
			fy = schooldirectory.OperationalFY(s.clock())
		}
		_, err := s.fieldOps.EnterSSA(ctx, p, fieldops.SSAEntryRequest{
			SchoolID:      req.GetSchoolId(),
			FY:            fy,
			Quarter:       vals["quarter"],
			Date:          s.clock(),
			NewEnrollment: enr,
			Scores:        scores,
			CollectorType: "staff",
		})
		if errors.Is(err, fieldops.ErrInvalidInput) {
			return &screensv1.SaveSchoolDrawerResponse{Saved: false, Error: "Enter a score from 0 to 10 for all eight interventions."}, true, nil
		}
		if err != nil {
			return nil, true, apierr.Internal(ctx, s.logger, err)
		}
		return &screensv1.SaveSchoolDrawerResponse{Saved: true, Message: "SSA scores saved."}, true, nil
	}

	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.SaveSchoolDrawerResponse{Saved: false, Error: "Your role cannot edit school details."}, true, nil
	}
	var enrPtr any = nil
	if raw := strings.TrimSpace(vals["enrollment"]); raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && n >= 0 {
			enrPtr = n
		}
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := s.clock()
	var ok bool
	if err := tx.QueryRow(ctx,
		`SELECT gateway_school_actions.update_school_details($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
		req.GetSchoolId(), vals["name"], vals["school_phone"], vals["primary_contact_name"],
		vals["primary_contact_phone"], enrPtr, vals["shipping_address"],
		vals["headteacher_name"], vals["director_name"],
		p.UserID, p.ActiveRole, now,
	).Scan(&ok); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	if !ok {
		return &screensv1.SaveSchoolDrawerResponse{Saved: false, Error: "School not found."}, true, nil
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action:      "school.details_updated",
		SubjectKind: audit.Text("school"),
		SubjectID:   audit.Text(req.GetSchoolId()),
		ActorID:     audit.Text(p.UserID),
		ActorRole:   audit.Text(p.ActiveRole),
		Success:     true,
		Payload: map[string]any{
			"name":       vals["name"],
			"enrollment": enrPtr,
		},
	}, now); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.SaveSchoolDrawerResponse{Saved: true, Message: "School details updated."}, true, nil
}

// ── Native Page Drawer GET (GetDrawer) ───────────────────────────────────────

func (s *Service) getPageDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	pathOnly := rawPath
	if i := strings.IndexByte(pathOnly, '?'); i >= 0 {
		pathOnly = pathOnly[:i]
	}

	if answer, served := s.weekOwnerDrawer(pathOnly); served {
		return answer, true, nil
	}
	if answer, served, err := s.accountabilityDrawerInGo(ctx, p, pathOnly); served {
		return answer, true, err
	}
	if answer, served, err := s.reimbursementDrawerInGo(ctx, p, pathOnly); served {
		return answer, true, err
	}
	if answer, served, err := s.extraWorkDrawerInGo(ctx, p, pathOnly); served {
		return answer, true, err
	}
	if answer, served, err := s.lifecycleDrawerInGo(ctx, p, pathOnly); served {
		return answer, true, err
	}
	if answer, served, err := s.bulkScheduleDrawerInGo(ctx, p, rawPath); served {
		return answer, true, err
	}
	if answer, served, err := s.exportDrawerInGo(ctx, p, rawPath); served {
		return answer, true, err
	}
	if answer, served, err := s.fieldFormInGo(ctx, p, rawPath); served {
		return answer, true, err
	}

	if m := schoolEditDrawer.FindStringSubmatch(pathOnly); m != nil {
		answer, served, err := s.getSchoolDrawerInGo(ctx, p, m[1], "edit")
		if err != nil || !served {
			return nil, served, err
		}
		return &screensv1.GetDrawerResponse{Drawer: answer.GetDrawer()}, true, nil
	}

	switch {
	case planDrawer(pathOnly, "reschedule"):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Reschedule Activity",
				HasRequired: true,
				SubmitLabel: "Reschedule",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("planned_date", "New Date", "date", "", true),
					fieldItem("reason", "Reason for rescheduling", "textarea", "", true),
				},
			},
		}, true, nil

	case planDrawer(pathOnly, "cancel"):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Cancel Activity",
				HasRequired: true,
				SubmitLabel: "Confirm Cancellation",
				CancelLabel: "Keep Activity",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("reason", "Cancellation reason", "textarea", "", true),
				},
			},
		}, true, nil

	case planDrawer(pathOnly, "complete"):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Complete Visit",
				HasRequired: true,
				SubmitLabel: "Submit Completed Visit",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("actual_delivery_date", "Actual Date", "date", s.clock().Format(time.DateOnly), true),
					fieldItem("salesforce_id", "Salesforce ID", "text", "", true),
					fieldItem("teachers_attended", "Teachers Attended", "number", "0", false),
					fieldItem("leaders_attended", "Leaders Attended", "number", "0", false),
					fieldItem("actual_observations", "Observations", "textarea", "", true),
					fieldItem("actual_outcome", "Outcome", "textarea", "", true),
				},
			},
		}, true, nil

	case planDrawer(pathOnly, "edit"):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Edit Activity",
				HasRequired: true,
				SubmitLabel: "Save Changes",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("planned_date", "Planned Date", "date", "", false),
					fieldItem("activity_purpose_text", "Purpose", "textarea", "", false),
					fieldItem("expected_outcome", "Expected Outcome", "textarea", "", false),
				},
			},
		}, true, nil

	case strings.Contains(pathOnly, "/pl/review-queue/"):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Programme Lead Review",
				HasRequired: true,
				SubmitLabel: "Submit Decision",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("note", "Review Note", "textarea", "", false),
				},
			},
		}, true, nil

	case reIADecide.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Impact Assessment Verification",
				HasRequired: true,
				SubmitLabel: "Save Decision",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("decision", "Decision", "select", "verified", true, "verified", "returned"),
					fieldItem("note", "Verification Note", "textarea", "", false),
				},
			},
		}, true, nil

	case reSSADecide.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Review SSA Record",
				HasRequired: true,
				SubmitLabel: "Save Decision",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("decision", "Decision", "select", "confirmed", true, "confirmed", "returned"),
					fieldItem("reason", "Review Note / Return Reason", "textarea", "", false),
				},
			},
		}, true, nil

	case rePartnerDate.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Schedule Partner Activity",
				HasRequired: true,
				SubmitLabel: "Save Date",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("date", "Delivery Date", "date", s.clock().Format(time.DateOnly), true),
				},
			},
		}, true, nil

	case rePartnerReturn.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Return Partner Assignment",
				HasRequired: true,
				SubmitLabel: "Return to Staff",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("reason", "Return Reason", "textarea", "", true),
				},
			},
		}, true, nil

	case reWeeklyTransition.MatchString(pathOnly), reAdvanceTransition.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Finance Action",
				HasRequired: false,
				SubmitLabel: "Confirm",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("amount", "Amount (UGX)", "number", "", false),
					fieldItem("returned", "Returned Amount (UGX)", "number", "0", false),
					fieldItem("method", "Payment Method", "select", "mobile_money", false, "mobile_money", "bank_transfer", "cash"),
					fieldItem("reference", "Reference / NetSuite ID", "text", "", false),
					fieldItem("reason", "Reason / Note", "textarea", "", false),
				},
			},
		}, true, nil

	case reLeaveDecide.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Leave Request Decision",
				HasRequired: true,
				SubmitLabel: "Save Decision",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("decision", "Decision", "select", "approved", true, "approved", "rejected", "hr_review"),
					fieldItem("note", "Decision Note", "textarea", "", false),
				},
			},
		}, true, nil

	case reEscalationDecide.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Leadership Escalation Decision",
				HasRequired: true,
				SubmitLabel: "Record Decision",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("decision", "Decision", "select", "resolved", true, "resolved", "in_progress", "escalated"),
					fieldItem("note", "Decision Note", "textarea", "", true),
				},
			},
		}, true, nil

	case reProfileEdit.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Edit Profile",
				HasRequired: true,
				SubmitLabel: "Save Profile",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("name", "Full Name", "text", p.Name, true),
					fieldItem("phone", "Phone Number", "tel", "", false),
				},
			},
		}, true, nil

	case reHelpFeedback.MatchString(pathOnly):
		return &screensv1.GetDrawerResponse{
			Drawer: &screensv1.PageDrawer{
				Title:       "Article Feedback",
				HasRequired: false,
				SubmitLabel: "Submit Feedback",
				CancelLabel: "Cancel",
				CanSubmit:   true,
				Items: []*screensv1.DrawerItem{
					fieldItem("helpful", "Was this helpful?", "select", "true", true, "true", "false"),
					fieldItem("comment", "Comments", "textarea", "", false),
				},
			},
		}, true, nil
	}

	return nil, false, nil
}

// isSSADrawer names the SSA entry drawer: the clients ask for "ssa-entry".
func isSSADrawer(kind string) bool { return kind == "ssa" || kind == "ssa-entry" }

// nativeSchoolDrawer is whether Go has its own form for this school drawer.
func nativeSchoolDrawer(kind string) bool { return kind == "edit" || isSSADrawer(kind) }

// planDrawer is whether path is the named drawer of an activity on My Plan.
// Other records have drawers of the same name (a school's, a cluster's, a
// partner's edit-drawer) with other forms.
func planDrawer(path, kind string) bool {
	m := planDrawerPath.FindStringSubmatch(path)
	return m != nil && m[1] == kind
}

var (
	planDrawerPath   = regexp.MustCompile(`^/my-plan/[A-Za-z0-9]{1,30}/(reschedule|cancel|complete|edit)-drawer/?$`)
	schoolEditDrawer = regexp.MustCompile(`^/schools/([A-Za-z0-9_-]{1,64})/edit-drawer/?$`)
)

func fieldItem(name, label, kind, value string, required bool, choices ...string) *screensv1.DrawerItem {
	var opts []*screensv1.DrawerOption
	for _, c := range choices {
		opts = append(opts, &screensv1.DrawerOption{Value: c, Label: c})
	}
	return &screensv1.DrawerItem{
		Kind: &screensv1.DrawerItem_Field{
			Field: &screensv1.DrawerField{
				Name:     name,
				Label:    label,
				Kind:     kind,
				Value:    value,
				Required: required,
				Options:  opts,
			},
		},
	}
}
