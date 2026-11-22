// Package objstore provides country-aware object storage for evidence files,
// exports, and reports. It supports S3-compatible buckets (AWS S3, DigitalOcean
// Spaces, Cloudflare R2, MinIO) via AWS SigV4 with a path-safe local directory
// fallback for single-node development.
package objstore

import (
	"context"
	"errors"
	"io"
	"path"
	"strings"
)

var (
	ErrNotFound   = errors.New("objstore: object not found")
	ErrInvalidKey = errors.New("objstore: invalid object key")
)

// ObjectMeta describes a stored object.
type ObjectMeta struct {
	Key         string
	Size        int64
	ContentType string
}

// Store stores and retrieves binary blobs keyed by logical path (e.g.
// "UG/evidence/2026/visit-123.pdf").
type Store interface {
	Put(ctx context.Context, key, contentType string, body io.Reader) (ObjectMeta, error)
	Get(ctx context.Context, key string) (io.ReadCloser, ObjectMeta, error)
	Delete(ctx context.Context, key string) error
	Backend() string
}

// CleanKey normalizes and validates a logical object key, rejecting path
// traversal and control characters.
func CleanKey(raw string) (string, error) {
	trimmed := strings.TrimSpace(strings.TrimLeft(raw, "/"))
	if trimmed == "" || strings.Contains(trimmed, "\\") || strings.ContainsRune(trimmed, 0) {
		return "", ErrInvalidKey
	}
	cleaned := path.Clean(trimmed)
	if cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, "../") || strings.Contains(cleaned, "/../") {
		return "", ErrInvalidKey
	}
	return cleaned, nil
}

// CountryKey namespaces an object key under an ISO country code (e.g. "UG").
func CountryKey(countryCode, category, name string) (string, error) {
	cc := strings.ToUpper(strings.TrimSpace(countryCode))
	if len(cc) != 2 {
		return "", ErrInvalidKey
	}
	return CleanKey(cc + "/" + strings.Trim(category, "/") + "/" + strings.TrimLeft(name, "/"))
}
