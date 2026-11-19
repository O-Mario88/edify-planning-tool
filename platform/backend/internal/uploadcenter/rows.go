package uploadcenter

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// errHandOn is a page Go hands on to the existing application.
var errHandOn = errors.New("uploadcenter: handed on")

// importLimit and documentLimit are the slices the adapters read
// ([:100] of each import table, [:300] of the documents).
const (
	importLimit   = 100
	documentLimit = 300
)

// row is UploadRow: one entry, whatever its record.
type row struct {
	recordType, id, title, owner, uploadedBy, context, version string
	processing, publication, acknowledgement, preview, next    string
	route, tab                                                 string
	uploadedAt                                                 time.Time
}

// reader is the person asking and what audience rules read of them.
type reader struct {
	userID, role, slug, country string
	doors                       Role
}

func names(ctx context.Context, db schooldirectory.Querier) (map[string]string, error) {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user"`)
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading names: %w", err)
	}
	out := map[string]string{}
	err = forEach(rows, func(r pgx.Rows) error {
		var id, name string
		if err := r.Scan(&id, &name); err != nil {
			return err
		}
		out[id] = name
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading names: %w", err)
	}
	return out, nil
}

func nameOr(names map[string]string, id, fallback string) string {
	if n, ok := names[id]; ok {
		return n
	}
	return fallback
}

func forEach(rows pgx.Rows, each func(pgx.Rows) error) error {
	defer rows.Close()
	for rows.Next() {
		if err := each(rows); err != nil {
			return err
		}
	}
	return rows.Err()
}

// imports is _structured_imports: the school and SSA import batches, newest
// first, for a reader who may upload them.
func imports(ctx context.Context, db schooldirectory.Querier, r reader, names map[string]string) ([]row, error) {
	out := []row{}
	if r.doors.SchoolUpload {
		rows, err := db.Query(ctx, `SELECT id, file_name, uploaded_by, status, total_rows, created_at
			FROM school_import_batch ORDER BY created_at DESC LIMIT $1`, importLimit)
		if err != nil {
			return nil, fmt.Errorf("uploadcenter: reading the school imports: %w", err)
		}
		err = forEach(rows, func(rs pgx.Rows) error {
			var id, file, by, status string
			var total int
			var at time.Time
			if err := rs.Scan(&id, &file, &by, &status, &total, &at); err != nil {
				return err
			}
			x := row{recordType: "school_import", id: id, title: file, owner: "School Import",
				uploadedBy: nameOr(names, by, by), uploadedAt: at, context: fmt.Sprintf("%d rows", total),
				processing: label(rules.SchoolImportStatuses, status), preview: "Structured preview",
				next: "View import results", route: "/schools/uploads/" + id + "/result", tab: "imports"}
			if status == "staged" {
				x.next, x.route = "Review rows", "/schools/upload/"+id+"/preview"
			}
			out = append(out, x)
			return nil
		})
		if err != nil {
			return nil, fmt.Errorf("uploadcenter: reading the school imports: %w", err)
		}
	}
	if r.doors.SSAUpload {
		rows, err := db.Query(ctx, `SELECT b.id, b.file_name, b.uploaded_by, b.status, b.total_rows, b.created_at,
			(SELECT COUNT(*) FROM ssa_import_row w WHERE w.batch_id = b.id AND w.status = 'unmatched')
			FROM ssa_import_batch b ORDER BY b.created_at DESC LIMIT $1`, importLimit)
		if err != nil {
			return nil, fmt.Errorf("uploadcenter: reading the SSA imports: %w", err)
		}
		err = forEach(rows, func(rs pgx.Rows) error {
			var id, file, by, status string
			var total, unmatched int
			var at time.Time
			if err := rs.Scan(&id, &file, &by, &status, &total, &at, &unmatched); err != nil {
				return err
			}
			x := row{recordType: "ssa_import", id: id, title: file, owner: "SSA Import",
				uploadedBy: nameOr(names, by, by), uploadedAt: at, context: fmt.Sprintf("%d rows", total),
				processing: label(rules.SSAImportStatuses, status), preview: "Structured preview",
				next: "View import results", route: "/ssa/upload/" + id + "/result/", tab: "imports"}
			if unmatched > 0 {
				x.context += fmt.Sprintf(" · %d unmatched", unmatched)
				x.next = "Resolve unmatched School IDs"
			}
			if status == "staged" {
				x.route = "/ssa/upload/" + id + "/preview/"
			}
			out = append(out, x)
			return nil
		})
		if err != nil {
			return nil, fmt.Errorf("uploadcenter: reading the SSA imports: %w", err)
		}
	}
	return out, nil
}

// rule is one audience rule.
type rule struct {
	role, country, partner, project, user string
	from                                  *time.Time
}

// String is DocumentAudienceRule.__str__.
func (r rule) String() string {
	parts := []string{}
	for _, f := range [][2]string{{"role", r.role}, {"country", r.country}, {"partner", r.partner}, {"user", r.user}} {
		if f[1] != "" {
			parts = append(parts, f[0]+"="+f[1])
		}
	}
	if len(parts) == 0 {
		return "everyone"
	}
	return strings.Join(parts, " ")
}

// matches is audience_matches for one reader: any rule whose every set
// field holds (a partner or project rule reached hands the page on).
func matches(rules []rule, r reader, today time.Time) (bool, error) {
	for _, x := range rules {
		switch {
		case x.from != nil && x.from.After(today):
		case x.role != "" && x.role != r.role && x.role != r.slug:
		case x.country != "" && x.country != r.country:
		case x.user != "" && x.user != r.userID:
		case x.partner != "" || x.project != "":
			return false, errHandOn
		default:
			return true, nil
		}
	}
	return false, nil
}

type document struct {
	id, title, slug, docType, status, createdBy string
	createdAt                                   time.Time
	mandatory                                   bool
	versionID                                   *string
	versionNumber                               *int
	preview                                     *string
	rules                                       []rule
	total, agreed                               int
}

func readDocuments(ctx context.Context, db schooldirectory.Querier) ([]*document, error) {
	rows, err := db.Query(ctx, `
		SELECT a.id, a.title, a.slug, a.document_type, a.status, COALESCE(a.created_by, ''), a.created_at,
		       a.acknowledgement_required OR a.agreement_required, v.id, v.version_number, v.preview_status,
		       (SELECT COUNT(*) FROM document_acknowledgement k WHERE k.version_id = v.id),
		       (SELECT COUNT(*) FROM document_acknowledgement k WHERE k.version_id = v.id AND k.state = 'agreed')
		FROM document_asset a
		LEFT JOIN document_version v ON v.id = a.current_version_id
		ORDER BY a.title
		LIMIT $1`, documentLimit)
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading the documents: %w", err)
	}
	docs := []*document{}
	byID := map[string]*document{}
	err = forEach(rows, func(rs pgx.Rows) error {
		d := &document{}
		if err := rs.Scan(&d.id, &d.title, &d.slug, &d.docType, &d.status, &d.createdBy, &d.createdAt, &d.mandatory,
			&d.versionID, &d.versionNumber, &d.preview, &d.total, &d.agreed); err != nil {
			return err
		}
		docs = append(docs, d)
		byID[d.id] = d
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading the documents: %w", err)
	}
	ids := make([]string, 0, len(docs))
	for _, d := range docs {
		ids = append(ids, d.id)
	}
	audiences, err := audienceRules(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	for id, list := range audiences {
		byID[id].rules = list
	}
	return docs, nil
}

// audienceRules reads each document's audience rules.
func audienceRules(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string][]rule, error) {
	rows, err := db.Query(ctx, `SELECT document_id, role, country, partner_id, project_id, user_id, effective_from
		FROM document_audience_rule WHERE document_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading the audiences: %w", err)
	}
	out := map[string][]rule{}
	err = forEach(rows, func(rs pgx.Rows) error {
		var doc string
		var x rule
		if err := rs.Scan(&doc, &x.role, &x.country, &x.partner, &x.project, &x.user, &x.from); err != nil {
			return err
		}
		out[doc] = append(out[doc], x)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading the audiences: %w", err)
	}
	return out, nil
}

// documents is _documents: the documents the reader administers, and the
// published ones aimed at them.
func documents(ctx context.Context, db schooldirectory.Querier, r reader, names map[string]string, today time.Time) ([]row, error) {
	docs, err := readDocuments(ctx, db)
	if err != nil {
		return nil, err
	}
	out := []row{}
	for _, d := range docs {
		training := slices.Contains(rules.TrainingTypes, d.docType)
		manages := (training && r.doors.TrainingCreate) || (!training && r.doors.DocumentsCreate)
		if !manages {
			aimed, err := matches(d.rules, r, today)
			if err != nil {
				return nil, err
			}
			if !aimed || (d.status != "published" && d.status != "effective") {
				continue
			}
		}
		x := row{recordType: d.docType, id: d.id, title: d.title, owner: "Document Library",
			uploadedBy: nameOr(names, d.createdBy, d.createdBy), uploadedAt: d.createdAt,
			publication: label(rules.DocumentStatuses, d.status), next: nextAction(d),
			route: "/documents/" + d.slug + "/", tab: "documents", version: "—", preview: "—"}
		if training {
			x.owner, x.tab = "Training Resource Library", "training"
		}
		audience := []string{}
		for i, rl := range d.rules {
			if i == 3 {
				break
			}
			audience = append(audience, rl.String())
		}
		x.context = strings.Join(audience, ", ")
		if x.context == "" {
			x.context = "No audience set"
		}
		if d.versionID != nil {
			x.version = "v" + strconv.Itoa(*d.versionNumber)
			x.preview = label(rules.PreviewStatuses, *d.preview)
		}
		if d.mandatory {
			x.acknowledgement = "Awaiting generation"
			if d.total > 0 {
				x.acknowledgement = fmt.Sprintf("%d/%d accepted", d.agreed, d.total)
			}
		}
		out = append(out, x)
	}
	return out, nil
}

// nextAction is _document_next_action.
func nextAction(d *document) string {
	switch d.status {
	case "draft":
		return "Submit for review"
	case "under_review":
		return "Review"
	case "approved":
		return "Publish"
	case "returned":
		return "Correct and resubmit"
	case "published":
		if d.mandatory {
			return "Monitor acknowledgements"
		}
		return "Published"
	case "effective":
		if d.mandatory {
			return "Monitor acknowledgements"
		}
		return "In effect"
	}
	return label(rules.DocumentStatuses, d.status)
}
