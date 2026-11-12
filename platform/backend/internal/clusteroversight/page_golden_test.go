package clusteroversight

import (
	"bytes"
	"compress/gzip"
	_ "embed"
	"encoding/json"
	"io"
	"net/url"
	"strings"
	"testing"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

//go:embed testdata/golden.json.gz
var goldenPacked []byte

// goldenCase is one page the existing application made of a set of records
// (testdata/golden.py): who read it, the records, and its feed's answer.
type goldenCase struct {
	Name      string            `json:"name"`
	Role      string            `json:"role"`
	ReaderIDs []string          `json:"reader_ids"`
	FY        string            `json:"fy"`
	Years     []string          `json:"years"`
	Today     string            `json:"today"`
	Query     map[string]string `json:"query"`
	Records   records           `json:"records"`
	Body      json.RawMessage   `json:"body"`
}

// The development seed reaches little of the Command Center: no published
// change rule, no school compared on SSA, enrolment or learning, one score
// and one level of maturity. These are pages the existing application's own
// code made of records that reach the rest, and Go must make the same page
// of the same records.
func TestThePageIsTheExistingApplicationsForTheSameRecords(t *testing.T) {
	unpacked, err := gzip.NewReader(bytes.NewReader(goldenPacked))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := io.ReadAll(unpacked)
	if err != nil {
		t.Fatal(err)
	}
	cases := []goldenCase{}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) < 10 {
		t.Fatalf("%d cases", len(cases))
	}
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			want := &screensv1.GetPageResponse{}
			if err := (protojson.UnmarshalOptions{}).Unmarshal(c.Body, want); err != nil {
				t.Fatalf("the existing answer does not fit the contract: %v", err)
			}
			query := url.Values{}
			for key, value := range c.Query {
				query.Set(key, value)
			}
			got := page(&c.Records, reader{doors: rules.Doors[c.Role], ids: c.ReaderIDs}, c.FY, c.Years, c.Today, query)
			if proto.Equal(got, want) {
				return
			}
			if len(got.GetBlocks()) != len(want.GetBlocks()) {
				t.Fatalf("%d blocks, want %d", len(got.GetBlocks()), len(want.GetBlocks()))
			}
			if !proto.Equal(got.GetHeader(), want.GetHeader()) {
				t.Errorf("header\n got %v\nwant %v", got.GetHeader(), want.GetHeader())
			}
			for i := range got.GetBlocks() {
				g, w := got.GetBlocks()[i], want.GetBlocks()[i]
				if proto.Equal(g, w) {
					continue
				}
				gt, wt := g.GetTable(), w.GetTable()
				if gt == nil || wt == nil || len(gt.GetRows()) != len(wt.GetRows()) {
					t.Errorf("block %d\n got %.900v\nwant %.900v", i, g, w)
					continue
				}
				shown := 0
				for r := range gt.GetRows() {
					for k := range gt.GetRows()[r].GetCells() {
						gc, wc := gt.GetRows()[r].GetCells()[k], wt.GetRows()[r].GetCells()[k]
						if !proto.Equal(gc, wc) && shown < 12 {
							shown++
							t.Errorf("%s, %s\n got %v\nwant %v", wt.GetRows()[r].GetCells()[0].GetText(), wt.GetColumns()[k].GetLabel(), gc, wc)
						}
					}
				}
				gt.Rows, wt.Rows = nil, nil
				if !proto.Equal(gt, wt) {
					t.Errorf("the table around its rows\n got %v\nwant %v", strings.TrimSpace(gt.String()), strings.TrimSpace(wt.String()))
				}
			}
		})
	}
}
