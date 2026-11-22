-- Spatial indexing on Go-owned school coordinate tables for fast radius,
-- bounding-box, and country-scoped map pin queries. Uses PostgreSQL's built-in
-- GiST point index (requires no PostGIS superuser extension) plus composite
-- country-scoped B-tree indexes.

CREATE INDEX IF NOT EXISTS school_location_country_bbox_idx
  ON field_routes.school_location (country_code, lat, lng);

CREATE INDEX IF NOT EXISTS school_location_gist_point_idx
  ON field_routes.school_location USING gist (point(lng, lat));

CREATE INDEX IF NOT EXISTS verified_location_country_bbox_idx
  ON field_routes.verified_location (country_code, lat, lng);

CREATE INDEX IF NOT EXISTS verified_location_gist_point_idx
  ON field_routes.verified_location USING gist (point(lng, lat));
