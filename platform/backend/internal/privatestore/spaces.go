package privatestore

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"
)

// SpacesConfig is the existing settings' SPACES_* values.
type SpacesConfig struct {
	Endpoint, Region, Bucket, Prefix string
	AccessKey, SecretKey             string
}

// maxObjectBytes bounds what Get reads back (the evidence ceiling and more).
const maxObjectBytes = 64 << 20

// emptyHash is SHA-256 of nothing.
const emptyHash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

// Spaces keeps files as private objects, path-style, signed with AWS
// Signature Version 4 (the S3 API DigitalOcean Spaces speaks).
func Spaces(cfg SpacesConfig, client *http.Client, now func() time.Time) Store {
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	if now == nil {
		now = time.Now
	}
	return spacesStore{cfg: cfg, client: client, now: now}
}

type spacesStore struct {
	cfg    SpacesConfig
	client *http.Client
	now    func() time.Time
}

func (s spacesStore) Provider() string { return "spaces" }

// objectURL is _spaces_options("private")'s key: <prefix>/private/<ns>/<name>.
func (s spacesStore) objectURL(ns, name string) (string, error) {
	if err := checkName(ns, name); err != nil {
		return "", err
	}
	key := strings.Trim(strings.Join([]string{strings.Trim(s.cfg.Prefix, "/"), "private", ns, name}, "/"), "/")
	return strings.TrimRight(s.cfg.Endpoint, "/") + "/" + url.PathEscape(s.cfg.Bucket) + "/" + key, nil
}

func (s spacesStore) do(ctx context.Context, method, target string, body []byte, header http.Header) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("privatestore: building the request: %w", err)
	}
	for k, v := range header {
		req.Header[k] = v
	}
	hash := emptyHash
	if len(body) > 0 {
		sum := sha256.Sum256(body)
		hash = hex.EncodeToString(sum[:])
	}
	signRequest(req, s.cfg.AccessKey, s.cfg.SecretKey, s.cfg.Region, "s3", s.now().UTC(), hash, true)
	resp, err := s.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("privatestore: reaching the store: %w", err)
	}
	return resp, nil
}

func (s spacesStore) Put(ctx context.Context, ns, name string, body []byte, contentType string) error {
	target, err := s.objectURL(ns, name)
	if err != nil {
		return err
	}
	// file_overwrite=False: a kept name is never written again.
	head, err := s.do(ctx, http.MethodHead, target, nil, nil)
	if err != nil {
		return err
	}
	_ = head.Body.Close()
	switch {
	case head.StatusCode == http.StatusOK:
		return ErrExists
	case head.StatusCode != http.StatusNotFound:
		return fmt.Errorf("privatestore: checking the object: status %d", head.StatusCode)
	}
	header := http.Header{}
	header.Set("x-amz-acl", "private")
	header.Set("Cache-Control", "private, no-store")
	if contentType != "" {
		header.Set("Content-Type", contentType)
	}
	resp, err := s.do(ctx, http.MethodPut, target, body, header)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("privatestore: storing the object: status %d", resp.StatusCode)
	}
	return nil
}

func (s spacesStore) Get(ctx context.Context, ns, name string) ([]byte, error) {
	target, err := s.objectURL(ns, name)
	if err != nil {
		return nil, err
	}
	resp, err := s.do(ctx, http.MethodGet, target, nil, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrNotFound
	}
	if resp.StatusCode/100 != 2 {
		return nil, fmt.Errorf("privatestore: reading the object: status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxObjectBytes))
	if err != nil {
		return nil, fmt.Errorf("privatestore: reading the object: %w", err)
	}
	return body, nil
}

func (s spacesStore) Delete(ctx context.Context, ns, name string) error {
	target, err := s.objectURL(ns, name)
	if err != nil {
		return err
	}
	resp, err := s.do(ctx, http.MethodDelete, target, nil, nil)
	if err != nil {
		return err
	}
	_ = resp.Body.Close()
	if resp.StatusCode/100 != 2 && resp.StatusCode != http.StatusNotFound {
		return fmt.Errorf("privatestore: deleting the object: status %d", resp.StatusCode)
	}
	return nil
}

// signRequest signs req with AWS Signature Version 4. withContentHash adds
// the x-amz-content-sha256 header S3 requires.
func signRequest(req *http.Request, accessKey, secretKey, region, service string, now time.Time, payloadHash string, withContentHash bool) {
	stamp := now.Format("20060102T150405Z")
	day := now.Format("20060102")
	req.Header.Set("X-Amz-Date", stamp)
	if withContentHash {
		req.Header.Set("X-Amz-Content-Sha256", payloadHash)
	}
	host := req.Host
	if host == "" {
		host = req.URL.Host
	}
	headers := map[string]string{"host": host}
	for name, values := range req.Header {
		lower := strings.ToLower(name)
		if strings.HasPrefix(lower, "x-amz-") || lower == "content-type" {
			headers[lower] = strings.TrimSpace(strings.Join(values, ","))
		}
	}
	names := make([]string, 0, len(headers))
	for name := range headers {
		names = append(names, name)
	}
	sort.Strings(names)
	var canonicalHeaders strings.Builder
	for _, name := range names {
		canonicalHeaders.WriteString(name + ":" + headers[name] + "\n")
	}
	signed := strings.Join(names, ";")
	path := req.URL.EscapedPath()
	if path == "" {
		path = "/"
	}
	canonical := strings.Join([]string{req.Method, path, req.URL.Query().Encode(), canonicalHeaders.String(), signed, payloadHash}, "\n")
	scope := day + "/" + region + "/" + service + "/aws4_request"
	sum := sha256.Sum256([]byte(canonical))
	toSign := strings.Join([]string{"AWS4-HMAC-SHA256", stamp, scope, hex.EncodeToString(sum[:])}, "\n")
	key := hmacOf([]byte("AWS4"+secretKey), day)
	key = hmacOf(key, region)
	key = hmacOf(key, service)
	key = hmacOf(key, "aws4_request")
	signature := hex.EncodeToString(hmacOf(key, toSign))
	req.Header.Set("Authorization", "AWS4-HMAC-SHA256 Credential="+accessKey+"/"+scope+", SignedHeaders="+signed+", Signature="+signature)
}

func hmacOf(key []byte, data string) []byte {
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(data))
	return mac.Sum(nil)
}
