package privatestore

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestALocalFileIsKeptUnderItsNamespace(t *testing.T) {
	root := t.TempDir()
	store := Local(root)
	ctx := context.Background()
	if err := store.Put(ctx, "evidence", "abc.pdf", []byte("%PDF-1.4"), "application/pdf"); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(root, "evidence", "abc.pdf"))
	if err != nil || string(got) != "%PDF-1.4" {
		t.Fatalf("got %q, %v", got, err)
	}
	read, err := store.Get(ctx, "evidence", "abc.pdf")
	if err != nil || string(read) != "%PDF-1.4" {
		t.Fatalf("read %q, %v", read, err)
	}
	if store.Provider() != "local" {
		t.Fatalf("provider %q", store.Provider())
	}
}

func TestAKeptFileIsNeverOverwritten(t *testing.T) {
	store := Local(t.TempDir())
	ctx := context.Background()
	if err := store.Put(ctx, "evidence", "abc.pdf", []byte("one"), ""); err != nil {
		t.Fatal(err)
	}
	if err := store.Put(ctx, "evidence", "abc.pdf", []byte("two"), ""); !errors.Is(err, ErrExists) {
		t.Fatalf("second put: %v", err)
	}
}

// private_storage.validate_stored_name and object_key: generated basenames
// only, never a path.
func TestOnlyGeneratedNamesAreKept(t *testing.T) {
	store := Local(t.TempDir())
	ctx := context.Background()
	for _, bad := range [][2]string{
		{"evidence", "../x.pdf"}, {"evidence", "a/b.pdf"}, {"evidence", ""}, {"evidence", ".hidden"},
		{"Evidence", "a.pdf"}, {"../up", "a.pdf"}, {"", "a.pdf"},
	} {
		if err := store.Put(ctx, bad[0], bad[1], []byte("x"), ""); !errors.Is(err, ErrBadName) {
			t.Fatalf("%q/%q: %v", bad[0], bad[1], err)
		}
	}
}

func TestADeletedFileIsGone(t *testing.T) {
	store := Local(t.TempDir())
	ctx := context.Background()
	_ = store.Put(ctx, "staged", "a.png", []byte("x"), "")
	if err := store.Delete(ctx, "staged", "a.png"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Get(ctx, "staged", "a.png"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("after delete: %v", err)
	}
}

// _spaces_options("private"): <prefix>/private/<namespace>/<name>, private,
// never cached, never overwritten.
func TestASpacesFileIsAPrivateObjectUnderThePrefix(t *testing.T) {
	var seen []*http.Request
	var body string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r)
		switch r.Method {
		case http.MethodHead:
			w.WriteHeader(http.StatusNotFound)
		case http.MethodPut:
			b, _ := io.ReadAll(r.Body)
			body = string(b)
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer server.Close()
	store := Spaces(SpacesConfig{
		Endpoint: server.URL, Region: "fra1", Bucket: "edify-files", Prefix: "edify",
		AccessKey: "AKIDEXAMPLE", SecretKey: "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
	}, server.Client(), func() time.Time { return time.Date(2026, 11, 24, 6, 0, 0, 0, time.UTC) })
	if err := store.Put(context.Background(), "evidence", "abc.pdf", []byte("%PDF"), "application/pdf"); err != nil {
		t.Fatal(err)
	}
	if len(seen) != 2 || seen[0].Method != http.MethodHead || seen[1].Method != http.MethodPut {
		t.Fatalf("requests %v", seen)
	}
	put := seen[1]
	if put.URL.Path != "/edify-files/edify/private/evidence/abc.pdf" || body != "%PDF" {
		t.Fatalf("path %s body %q", put.URL.Path, body)
	}
	if put.Header.Get("x-amz-acl") != "private" || put.Header.Get("Cache-Control") != "private, no-store" ||
		put.Header.Get("Content-Type") != "application/pdf" {
		t.Fatalf("headers %v", put.Header)
	}
	authz := put.Header.Get("Authorization")
	if !strings.HasPrefix(authz, "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261124/fra1/s3/aws4_request,") ||
		!strings.Contains(authz, "SignedHeaders=") || !strings.Contains(authz, "Signature=") {
		t.Fatalf("authorization %q", authz)
	}
	if store.Provider() != "spaces" {
		t.Fatalf("provider %q", store.Provider())
	}
}

// The AWS Signature Version 4 test suite's GET example (get-vanilla), with
// the service set to "service": the signing is the standard one.
func TestSigningIsAWSSignatureVersion4(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "https://example.amazonaws.com/", nil)
	req.Header.Set("X-Amz-Date", "20150830T123600Z")
	signRequest(req, "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "us-east-1", "service",
		time.Date(2015, 8, 30, 12, 36, 0, 0, time.UTC), emptyHash, false)
	want := "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, " +
		"SignedHeaders=host;x-amz-date, Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
	if got := req.Header.Get("Authorization"); got != want {
		t.Fatalf("got  %s\nwant %s", got, want)
	}
}
