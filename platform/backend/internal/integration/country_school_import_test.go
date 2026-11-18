//go:build integration

package integration

import (
	"context"
	"fmt"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
)

// Previewing a school list (docs/migration/80 §27) through the gateway, as
// an Admin: an existing Ugandan school's row is "existing" and placed in its
// own region, district and sub-county; a new School ID in the same place is
// ready; a row with no region is rejected, as Uganda requires one; the
// Ugandan School ID offered for Kenya is rejected as another country's. A
// Country Director may not preview, and a file that is not a school list is
// refused. Nothing is written.
func TestPreviewingASchoolListThroughTheGateway(t *testing.T) {
	ctx := context.Background()
	var adminID, cdID, schoolID, name, region, district, subCounty string
	var before int64
	if err := admin.QueryRow(ctx, `SELECT (SELECT id FROM "user" WHERE email = 'admin@edify.org'),
  (SELECT id FROM "user" WHERE email = 'cd@edify.org'), s.school_id, s.name, r.name, d.name, sc.name,
  (SELECT count(*) FROM school)
FROM school s JOIN district d ON d.id = s.district_id JOIN region r ON r.id = d.region_id
JOIN sub_county sc ON sc.id = s.sub_county_id AND sc.district_id = d.id
WHERE s.deleted_at IS NULL AND btrim(s.school_id) <> '' AND r.country = 'Uganda'
  AND (SELECT count(*) FROM district x WHERE lower(x.name) = lower(d.name)) = 1
  AND (SELECT count(*) FROM sub_county x WHERE x.district_id = d.id AND lower(x.name) = lower(sc.name)) = 1
ORDER BY s.id LIMIT 1`).Scan(&adminID, &cdID, &schoolID, &name, &region, &district, &subCounty, &before); err != nil {
		t.Fatal(err)
	}
	asAdmin, asCD := token(t, adminID, "Admin", time.Hour), token(t, cdID, "CountryDirector", time.Hour)
	client := countriesClient()
	file := fmt.Sprintf("School ID,School Name,Region,District,Sub County,EMIS Number\n"+
		"%s,%q,%s,%s,%s,EM-1\nGCIMP-NEW,Gcimp New School,%s,%s,%s,EM-2\nGCIMP-NOREGION,Gcimp Nowhere,,%s,,\n",
		schoolID, name, region, district, subCounty, region, district, subCounty, district)
	preview := func(code, bearer string, content []byte) (*countriesv1.PreviewSchoolImportResponse, error) {
		got, err := client.PreviewSchoolImport(ctx, authed(&countriesv1.PreviewSchoolImportRequest{CountryCode: code,
			FileName: "schools.csv", Content: content}, bearer))
		if err != nil {
			return nil, err
		}
		return got.Msg, nil
	}
	ug, err := preview("UG", asAdmin, []byte(file))
	if err != nil {
		t.Fatal(err)
	}
	if len(ug.GetRows()) != 3 {
		t.Fatalf("Uganda's preview: %d rows", len(ug.GetRows()))
	}
	held, fresh, nowhere := ug.GetRows()[0], ug.GetRows()[1], ug.GetRows()[2]
	if held.GetStatus() != "existing" || strings.Join(held.GetUnits(), "/") != region+"/"+district+"/"+subCounty || held.GetNationalId() != "EM-1" {
		t.Errorf("the existing school: %+v", held)
	}
	if fresh.GetStatus() != "ready" || strings.Join(fresh.GetUnits(), "/") != region+"/"+district+"/"+subCounty || fresh.GetSchoolId() != "GCIMP-NEW" {
		t.Errorf("the new school: %+v", fresh)
	}
	if nowhere.GetStatus() != "rejected" || !strings.Contains(strings.Join(nowhere.GetMessages(), "; "), "Region is required") {
		t.Errorf("the school with no region: %+v", nowhere)
	}
	if c := ug.GetCounts(); c.GetExisting() != 1 || c.GetReady() != 1 || c.GetRejected() != 1 {
		t.Errorf("Uganda's counts: %+v", c)
	}

	ke, err := preview("KE", asAdmin, []byte(fmt.Sprintf("School ID,School Name\n%s,%q\n", schoolID, name)))
	if err != nil {
		t.Fatal(err)
	}
	if r := ke.GetRows()[0]; r.GetStatus() != "rejected" || !strings.Contains(strings.Join(r.GetMessages(), "; "), "another country") {
		t.Errorf("a Ugandan School ID offered for Kenya: %+v", r)
	}
	if _, err := preview("UG", asCD, []byte(file)); connect.CodeOf(err) != connect.CodePermissionDenied {
		t.Errorf("a Country Director previewing: %v", err)
	}
	if _, err := preview("UG", asAdmin, []byte("Name\nx\n")); connect.CodeOf(err) != connect.CodeInvalidArgument {
		t.Errorf("a file with no School ID column: %v", err)
	}
	var after int64
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM school`).Scan(&after); err != nil {
		t.Fatal(err)
	}
	if after != before {
		t.Errorf("a preview changed the schools: %d before, %d after", before, after)
	}
}
