package objstore

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
	"strings"
	"time"
)

// S3Config configures an S3-compatible bucket (AWS S3, DigitalOcean Spaces,
// Cloudflare R2, MinIO).
type S3Config struct {
	Endpoint  string
	Bucket    string
	Region    string
	AccessKey string
	SecretKey string
}

// S3Store speaks the S3 REST API with AWS Signature Version 4 using stdlib
// only (zero external SDK dependency).
type S3Store struct {
	cfg    S3Config
	client *http.Client
	now    func() time.Time
}

// NewS3 validates cfg and returns an S3Store.
func NewS3(cfg S3Config) (*S3Store, error) {
	cfg.Endpoint = strings.TrimRight(strings.TrimSpace(cfg.Endpoint), "/")
	cfg.Bucket = strings.TrimSpace(cfg.Bucket)
	cfg.Region = strings.TrimSpace(cfg.Region)
	if cfg.Region == "" {
		cfg.Region = "us-east-1"
	}
	if cfg.Endpoint == "" || cfg.Bucket == "" || cfg.AccessKey == "" || cfg.SecretKey == "" {
		return nil, fmt.Errorf("objstore: endpoint, bucket, access key and secret key are required for S3")
	}
	return &S3Store{
		cfg:    cfg,
		client: &http.Client{Timeout: 30 * time.Second},
		now:    time.Now,
	}, nil
}

func (s *S3Store) Backend() string { return "s3" }

func (s *S3Store) objectURL(key string) (string, string, error) {
	clean, err := CleanKey(key)
	if err != nil {
		return "", "", err
	}
	parts := strings.Split(clean, "/")
	for i, p := range parts {
		parts[i] = url.PathEscape(p)
	}
	canonicalPath := "/" + url.PathEscape(s.cfg.Bucket) + "/" + strings.Join(parts, "/")
	return clean, s.cfg.Endpoint + canonicalPath, nil
}

func (s *S3Store) sign(req *http.Request, payloadHash string) {
	t := s.now().UTC()
	amzDate := t.Format("20060102T150405Z")
	dateStamp := t.Format("20060102")

	req.Header.Set("Host", req.URL.Host)
	req.Header.Set("X-Amz-Content-Sha256", payloadHash)
	req.Header.Set("X-Amz-Date", amzDate)

	canonicalHeaders := fmt.Sprintf("host:%s\nx-amz-content-sha256:%s\nx-amz-date:%s\n",
		req.URL.Host, payloadHash, amzDate)
	signedHeaders := "host;x-amz-content-sha256;x-amz-date"
	canonicalRequest := strings.Join([]string{
		req.Method,
		req.URL.EscapedPath(),
		req.URL.RawQuery,
		canonicalHeaders,
		signedHeaders,
		payloadHash,
	}, "\n")

	scope := fmt.Sprintf("%s/%s/s3/aws4_request", dateStamp, s.cfg.Region)
	stringToSign := strings.Join([]string{
		"AWS4-HMAC-SHA256",
		amzDate,
		scope,
		sha256Hex([]byte(canonicalRequest)),
	}, "\n")

	kDate := hmacSHA256([]byte("AWS4"+s.cfg.SecretKey), dateStamp)
	kRegion := hmacSHA256(kDate, s.cfg.Region)
	kService := hmacSHA256(kRegion, "s3")
	kSigning := hmacSHA256(kService, "aws4_request")
	sig := hex.EncodeToString(hmacSHA256(kSigning, stringToSign))

	req.Header.Set("Authorization", fmt.Sprintf(
		"AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s",
		s.cfg.AccessKey, scope, signedHeaders, sig,
	))
}

func (s *S3Store) Put(ctx context.Context, key, contentType string, body io.Reader) (ObjectMeta, error) {
	clean, target, err := s.objectURL(key)
	if err != nil {
		return ObjectMeta{}, err
	}
	payload, err := io.ReadAll(body)
	if err != nil {
		return ObjectMeta{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, target, bytes.NewReader(payload))
	if err != nil {
		return ObjectMeta{}, err
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	s.sign(req, sha256Hex(payload))
	resp, err := s.client.Do(req)
	if err != nil {
		return ObjectMeta{}, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 {
		return ObjectMeta{}, fmt.Errorf("objstore: s3 put %s: status %d", clean, resp.StatusCode)
	}
	return ObjectMeta{Key: clean, Size: int64(len(payload)), ContentType: contentType}, nil
}

func (s *S3Store) Get(ctx context.Context, key string) (io.ReadCloser, ObjectMeta, error) {
	clean, target, err := s.objectURL(key)
	if err != nil {
		return nil, ObjectMeta{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, ObjectMeta{}, err
	}
	s.sign(req, sha256Hex(nil))
	resp, err := s.client.Do(req)
	if err != nil {
		return nil, ObjectMeta{}, err
	}
	if resp.StatusCode == http.StatusNotFound {
		_ = resp.Body.Close()
		return nil, ObjectMeta{}, ErrNotFound
	}
	if resp.StatusCode >= 300 {
		_ = resp.Body.Close()
		return nil, ObjectMeta{}, fmt.Errorf("objstore: s3 get %s: status %d", clean, resp.StatusCode)
	}
	return resp.Body, ObjectMeta{
		Key:         clean,
		Size:        resp.ContentLength,
		ContentType: resp.Header.Get("Content-Type"),
	}, nil
}

func (s *S3Store) Delete(ctx context.Context, key string) error {
	clean, target, err := s.objectURL(key)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, target, nil)
	if err != nil {
		return err
	}
	s.sign(req, sha256Hex(nil))
	resp, err := s.client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 && resp.StatusCode != http.StatusNotFound {
		return fmt.Errorf("objstore: s3 delete %s: status %d", clean, resp.StatusCode)
	}
	return nil
}

func sha256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

func hmacSHA256(key []byte, data string) []byte {
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte(data))
	return mac.Sum(nil)
}
