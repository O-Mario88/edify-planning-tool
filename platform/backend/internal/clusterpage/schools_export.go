package clusterpage

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The Cluster Profile's Export schools (cluster_views.cluster_schools_export_view
// with clusters.services.cluster_school_contacts): each school the Cluster
// Page lists with its ID, name, phone, primary contact and shipping address,
// one file named after the cluster, for whoever may open the cluster.

var (
	schoolsExportTarget  = regexp.MustCompile(`^/clusters/([A-Za-z0-9_-]{1,64})/schools/export$`)
	schoolContactHeaders = []string{"School ID", "School Name", "Phone", "Primary Contact", "Shipping Address"}
	schoolContactWidths  = []float64{14, 40, 18, 28, 48}
	// phoneLike is _PHONE_LIKE: a number as staff type a phone.
	phoneLike = regexp.MustCompile(`^[+-]?[\d\s()\-]+$`)
	// unsafeStem is what the file name drops of a cluster's name.
	unsafeStem = regexp.MustCompile(`[^A-Za-z0-9_\- ]`)
)

// clusterNotFound is the view's Http404 ("Cluster not found.").
type clusterNotFound struct{}

func (clusterNotFound) Error() string  { return "Cluster not found." }
func (clusterNotFound) NotFound() bool { return true }

// SchoolsExportRoute names the export for its target, or none.
func (s *Service) SchoolsExportRoute(target string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
	m := schoolsExportTarget.FindStringSubmatch(target)
	if m == nil {
		return nil, false
	}
	return func(ctx context.Context, p auth.Principal, _ url.Values) (string, []workbook.Sheet, bool, error) {
		return s.schoolsExport(ctx, p, m[1])
	}, true
}

func (s *Service) schoolsExport(ctx context.Context, p auth.Principal, clusterID string) (string, []workbook.Sheet, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, "/clusters/"+clusterID+"/schools/export") {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return "", nil, true, err
	}
	var c clusterRef
	err = s.db.QueryRow(ctx, `
SELECT id, COALESCE(name, ''), COALESCE(responsible_staff_id, ''), COALESCE(district_id, ''), COALESCE(region_id, '')
FROM cluster WHERE id = $1 AND deleted_at IS NULL`, clusterID).Scan(&c.id, &c.name, &c.owner, &c.districtID, &c.regionID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil, true, clusterNotFound{}
	}
	if err != nil {
		return "", nil, true, fmt.Errorf("clusterpage: reading the cluster: %w", err)
	}
	if ok, err := readable(ctx, s.db, scope, c); err != nil || !ok {
		if err == nil {
			err = clusterNotFound{}
		}
		return "", nil, true, err
	}
	rows := [][]workbook.Cell{}
	err = each(ctx, s.db, "the cluster's school contacts", `
SELECT s.school_id, s.name, s.school_phone, s.primary_contact_name, s.shipping_address
FROM school s
WHERE s.cluster_id = $1 AND s.deleted_at IS NULL AND s.operational_status = ANY($2)
  AND NOT (s.school_type = ANY($3) AND s.school_type IS NOT NULL)
ORDER BY s.name`, func(r pgx.Rows) error {
		values := make([]*string, 5)
		if err := r.Scan(&values[0], &values[1], &values[2], &values[3], &values[4]); err != nil {
			return err
		}
		row := make([]workbook.Cell, len(values))
		for i, v := range values {
			row[i] = workbook.Empty()
			if v != nil {
				row[i] = workbook.Text(contactText(*v))
			}
		}
		rows = append(rows, row)
		return nil
	}, c.id, rules.OperatingStatuses, rules.OwnTableSchoolTypes)
	if err != nil {
		return "", nil, true, err
	}
	stem := strings.TrimSpace(unsafeStem.ReplaceAllString(c.name, ""))
	if stem == "" {
		stem = "Cluster"
	}
	return stem + " schools", []workbook.Sheet{{Title: "Schools", Headers: schoolContactHeaders, Rows: rows,
		Widths: schoolContactWidths}}, true, nil
}

// contactText is clusters.services._spreadsheet_text: a leading =, @, tab or
// return quoted, and a leading + or - unless the value is a phone number.
func contactText(value string) string {
	trimmed := strings.TrimLeft(value, " \t\n\r\x0b\x0c")
	if trimmed == "" {
		return value
	}
	switch head := trimmed[0]; {
	case head == '=' || head == '@' || head == '\t' || head == '\r':
		return "'" + value
	case (head == '+' || head == '-') && !phoneLike.MatchString(strings.TrimSpace(value)):
		return "'" + value
	}
	return value
}
