package config

import (
	"fmt"
	"net/url"
	"strings"
)

const (
	envRedisURL     = "EDIFY_REDIS_URL"
	envObjEndpoint  = "EDIFY_OBJECT_STORAGE_ENDPOINT"
	envObjBucket    = "EDIFY_OBJECT_STORAGE_BUCKET"
	envObjRegion    = "EDIFY_OBJECT_STORAGE_REGION"
	envObjAccessKey = "EDIFY_OBJECT_STORAGE_ACCESS_KEY"
	envObjSecretKey = "EDIFY_OBJECT_STORAGE_SECRET_KEY"
	envEvidenceDir  = "EDIFY_EVIDENCE_STORAGE_DIR"
)

// ObjectStorage configures S3-compatible object storage (S3, Spaces, R2, MinIO)
// with a local directory fallback for single-node development.
type ObjectStorage struct {
	Endpoint    string
	Bucket      string
	Region      string
	AccessKey   string
	SecretKey   string
	EvidenceDir string
}

// UseS3 reports whether S3-compatible credentials are configured.
func (o ObjectStorage) UseS3() bool {
	return o.Endpoint != "" && o.Bucket != "" && o.AccessKey != "" && o.SecretKey != ""
}

func loadInfra(env Environment, getenv func(string) string) (string, ObjectStorage, error) {
	redisURL := strings.TrimSpace(getenv(envRedisURL))
	if redisURL != "" {
		parsed, err := url.Parse(redisURL)
		if err != nil || (parsed.Scheme != "redis" && parsed.Scheme != "rediss") || parsed.Hostname() == "" {
			return "", ObjectStorage{}, fmt.Errorf("config: %s must be a redis:// or rediss:// URL", envRedisURL)
		}
		if env == Staging && parsed.Scheme != "rediss" {
			return "", ObjectStorage{}, fmt.Errorf("config: %s must use TLS (rediss://) in staging", envRedisURL)
		}
	}

	obj := ObjectStorage{
		Endpoint:    strings.TrimRight(strings.TrimSpace(getenv(envObjEndpoint)), "/"),
		Bucket:      strings.TrimSpace(getenv(envObjBucket)),
		Region:      firstNonEmpty(getenv(envObjRegion), "us-east-1"),
		AccessKey:   strings.TrimSpace(getenv(envObjAccessKey)),
		SecretKey:   strings.TrimSpace(getenv(envObjSecretKey)),
		EvidenceDir: strings.TrimSpace(getenv(envEvidenceDir)),
	}
	anyS3 := obj.Endpoint != "" || obj.Bucket != "" || obj.AccessKey != "" || obj.SecretKey != ""
	if anyS3 && !obj.UseS3() {
		return "", ObjectStorage{}, fmt.Errorf("config: S3 object storage requires endpoint, bucket, access key and secret key together")
	}
	if obj.UseS3() && env == Staging && !strings.HasPrefix(obj.Endpoint, "https://") {
		return "", ObjectStorage{}, fmt.Errorf("config: %s must use https:// in staging", envObjEndpoint)
	}
	return redisURL, obj, nil
}
