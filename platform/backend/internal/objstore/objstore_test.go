package objstore

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func TestLocalStoreRoundTripAndTraversalGuard(t *testing.T) {
	store, err := NewLocal(t.TempDir())
	if err != nil {
		t.Fatalf("NewLocal: %v", err)
	}
	ctx := context.Background()
	key, err := CountryKey("ug", "evidence", "visit-1.txt")
	if err != nil || key != "UG/evidence/visit-1.txt" {
		t.Fatalf("CountryKey: (%q, %v)", key, err)
	}
	meta, err := store.Put(ctx, key, "text/plain", strings.NewReader("verified-photo"))
	if err != nil || meta.Size != 14 {
		t.Fatalf("Put: (%+v, %v)", meta, err)
	}
	rc, _, err := store.Get(ctx, key)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	got, _ := io.ReadAll(rc)
	_ = rc.Close()
	if string(got) != "verified-photo" {
		t.Fatalf("got %q", string(got))
	}
	if err := store.Delete(ctx, key); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, _, err := store.Get(ctx, key); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
	if _, err := store.Put(ctx, "../escape.txt", "text/plain", bytes.NewReader(nil)); !errors.Is(err, ErrInvalidKey) {
		t.Fatalf("expected ErrInvalidKey on traversal, got %v", err)
	}
}

func TestS3StoreSigV4RoundTrip(t *testing.T) {
	var mu sync.Mutex
	objects := map[string][]byte{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.Header.Get("Authorization"), "AWS4-HMAC-SHA256 Credential=AKIA_TEST/") {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		if r.Header.Get("X-Amz-Date") == "" || r.Header.Get("X-Amz-Content-Sha256") == "" {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		switch r.Method {
		case http.MethodPut:
			b, _ := io.ReadAll(r.Body)
			objects[r.URL.Path] = b
			w.WriteHeader(http.StatusOK)
		case http.MethodGet:
			b, ok := objects[r.URL.Path]
			if !ok {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			_, _ = w.Write(b)
		case http.MethodDelete:
			delete(objects, r.URL.Path)
			w.WriteHeader(http.StatusNoContent)
		}
	}))
	defer srv.Close()

	store, err := NewS3(S3Config{
		Endpoint:  srv.URL,
		Bucket:    "edify-evidence",
		Region:    "fra1",
		AccessKey: "AKIA_TEST",
		SecretKey: "SECRET_TEST",
	})
	if err != nil {
		t.Fatalf("NewS3: %v", err)
	}
	ctx := context.Background()
	if _, err := store.Put(ctx, "KE/reports/q1.pdf", "application/pdf", strings.NewReader("%PDF-1.7")); err != nil {
		t.Fatalf("Put: %v", err)
	}
	rc, _, err := store.Get(ctx, "KE/reports/q1.pdf")
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	b, _ := io.ReadAll(rc)
	_ = rc.Close()
	if string(b) != "%PDF-1.7" {
		t.Fatalf("got %q", string(b))
	}
	if err := store.Delete(ctx, "KE/reports/q1.pdf"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, _, err := store.Get(ctx, "KE/reports/q1.pdf"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}
