package countryconfig

import (
	"context"
	"errors"
	"strings"

	"connectrpc.com/connect"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolimport"
)

// PreviewSchoolImport says what each row of a country's school list would
// come to, placed in that country's geography (docs/migration/80 §27). Only
// an Admin previews, for any country they may see; nothing is written, so
// Uganda's list may be previewed too.
func (s *Service) PreviewSchoolImport(ctx context.Context, req *connect.Request[countriesv1.PreviewSchoolImportRequest]) (*connect.Response[countriesv1.PreviewSchoolImportResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	if p.ActiveRole != roleAdmin {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: only an Admin previews a school list.")
	}
	c, err := s.seen(ctx, p, strings.TrimSpace(req.Msg.GetCountryCode()))
	if err != nil {
		return nil, err
	}
	var refused schoolimport.ErrFile
	sheet, err := schoolimport.Read(req.Msg.GetFileName(), req.Msg.GetContent())
	if errors.As(err, &refused) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, refused.Error())
	}
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	place, err := schoolimport.LoadPlace(ctx, s.db, c.ID, schoolimport.SchoolIDs(sheet))
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	result, err := schoolimport.Preview(sheet, place)
	if errors.As(err, &refused) {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, refused.Error())
	}
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	out := &countriesv1.PreviewSchoolImportResponse{
		Columns: make([]*countriesv1.SchoolImportColumn, 0, len(result.Columns)),
		Rows:    make([]*countriesv1.SchoolImportRow, 0, len(result.Rows)),
		Counts: &countriesv1.SchoolImportCounts{
			Ready: int32(result.Counts[schoolimport.Ready]), Existing: int32(result.Counts[schoolimport.Existing]),
			Duplicate: int32(result.Counts[schoolimport.Duplicate]), Rejected: int32(result.Counts[schoolimport.Rejected]),
			Skipped: int32(result.Counts[schoolimport.Skipped]),
		},
	}
	for _, col := range result.Columns {
		out.Columns = append(out.Columns, &countriesv1.SchoolImportColumn{Header: col.Header, TakenAs: col.TakenAs})
	}
	for _, r := range result.Rows {
		out.Rows = append(out.Rows, &countriesv1.SchoolImportRow{
			Line: int32(r.Line), SchoolId: r.SchoolID, Name: r.Name, NationalId: r.NationalID, Status: r.Status,
			SchoolType: r.SchoolType, Units: r.Units, Messages: r.Messages,
		})
	}
	s.logger.InfoContext(ctx, "school list previewed", "country", c.Code, "rows", len(result.Rows), "by", p.UserID)
	return connect.NewResponse(out), nil
}
