// Package profilepage builds /profile (apps.frontend.views.staff_views.profile_view,
// templates/pages/profile/index.html) directly from PostgreSQL so Go no longer
// hands the user profile page back to the existing Django application.
package profilepage

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the user profile page's route.
const Path = "/profile"

const (
	recentLimit    = 5
	nameMaxLength  = 255
	phoneMaxLength = 64
)

// completedWorkStatuses mirrors apps.core.activity_types.COMPLETED_WORK_STATUSES.
var completedWorkStatuses = []string{
	"ia_verified",
	"closed",
	"accountant_confirmed",
	"completed",
}

// apMonths mirrors Django's default DATE_FORMAT ("N j, Y") month abbreviations.
var apMonths = [...]string{
	"Jan.", "Feb.", "March", "April", "May", "June",
	"July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.",
}

// Service answers /profile from the existing database.
type Service struct {
	db schooldirectory.Querier
}

// NewService returns a /profile page builder over db.
func NewService(db schooldirectory.Querier) *Service {
	return &Service{db: db}
}

type recentActivity struct {
	id          string
	status      string
	plannedDate *time.Time
	schoolID    string
	schoolName  string
}

// Build answers /profile for any signed-in reader. Every other path is not its
// own and returns served = false.
func (s *Service) Build(
	ctx context.Context, p auth.Principal, path string, _ url.Values,
) (*screensv1.GetPageResponse, bool, error) {
	if path != Path && path != Path+"/" {
		return nil, false, nil
	}
	var phone string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(phone, '') FROM "user" WHERE id = $1`, p.UserID).Scan(&phone); err != nil && err != pgx.ErrNoRows {
		return nil, true, fmt.Errorf("profilepage: reading account phone: %w", err)
	}
	var total, completed int
	if err := s.db.QueryRow(ctx, `
SELECT count(*),
       count(*) FILTER (WHERE status = ANY($2))
FROM activity
WHERE responsible_staff_id = $1 AND deleted_at IS NULL`,
		p.UserID, completedWorkStatuses).Scan(&total, &completed); err != nil {
		return nil, true, fmt.Errorf("profilepage: counting activities: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.status, ''), a.planned_date, COALESCE(a.school_id, ''), COALESCE(s.name, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
WHERE a.responsible_staff_id = $1 AND a.deleted_at IS NULL
ORDER BY a.updated_at DESC
LIMIT $2`, p.UserID, recentLimit)
	if err != nil {
		return nil, true, fmt.Errorf("profilepage: reading recent activities: %w", err)
	}
	recent, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (recentActivity, error) {
		var a recentActivity
		err := r.Scan(&a.id, &a.status, &a.plannedDate, &a.schoolID, &a.schoolName)
		return a, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("profilepage: scanning recent activities: %w", err)
	}
	return buildPage(p, phone, total, completed, recent), true, nil
}

func buildPage(p auth.Principal, phone string, total, completed int, recent []recentActivity) *screensv1.GetPageResponse {
	rate := 0
	if total > 0 {
		rate = int(math.RoundToEven(float64(completed) / float64(total) * 100))
	}
	nameMax := int32(nameMaxLength)
	phoneMax := int32(phoneMaxLength)
	blocks := []*screensv1.PageBlock{
		{
			Kind: &screensv1.PageBlock_Strip{
				Strip: &screensv1.PageStrip{
					Title: "Performance overview",
					Metrics: []*screensv1.PageMetric{
						{Label: "Total Activities", Value: strconv.Itoa(total)},
						{Label: "Completed", Value: strconv.Itoa(completed)},
						{Label: "Completion Rate", Value: fmt.Sprintf("%d%%", rate)},
					},
				},
			},
		},
		{
			Kind: &screensv1.PageBlock_Form{
				Form: &screensv1.PageForm{
					Title: "Account Details",
					Text:  "Your name and phone number are yours to change. Email, status and roles are set by an administrator.",
					Items: []*screensv1.PageFormItem{
						{
							Kind: &screensv1.PageFormItem_Field{
								Field: &screensv1.DrawerField{
									Name:      "name",
									Label:     "Full Name",
									Kind:      "text",
									Value:     p.Name,
									Required:  true,
									MaxLength: &nameMax,
								},
							},
						},
						{
							Kind: &screensv1.PageFormItem_Field{
								Field: &screensv1.DrawerField{
									Name:        "phone",
									Label:       "Phone Number",
									Kind:        "tel",
									Value:       phone,
									Placeholder: "Not set",
									MaxLength:   &phoneMax,
								},
							},
						},
					},
					SubmitLabel: "Save Changes",
					Key:         Path,
				},
			},
		},
	}
	if len(recent) > 0 {
		links := make([]*screensv1.PageLink, 0, len(recent))
		for _, a := range recent {
			text, href := "→", "/my-plan/"+a.id
			if a.schoolID != "" {
				text, href = a.schoolName, "/schools/"+a.schoolID
			}
			links = append(links, &screensv1.PageLink{
				Text:    text,
				Href:    href,
				Caption: formatPlannedDate(a.plannedDate) + " · " + a.status,
			})
		}
		blocks = append(blocks, &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Panel{
				Panel: &screensv1.PagePanel{
					Title: "Recent Activity",
					Items: []*screensv1.PagePanelItem{
						{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
					},
				},
			},
		})
	}
	if len(p.Roles) > 1 {
		blocks = append(blocks, &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Panel{
				Panel: &screensv1.PagePanel{
					Title: "Switch Active Role",
				},
			},
		})
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Account",
			Title:       p.Name,
			Description: p.Email,
		},
		Blocks:  blocks,
		WebPath: Path,
	}
}

func formatPlannedDate(d *time.Time) string {
	if d == nil {
		return "No date"
	}
	return fmt.Sprintf("%s %d, %d", apMonths[d.Month()-1], d.Day(), d.Year())
}
