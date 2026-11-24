// Package privatestore keeps user-uploaded files where the existing
// application keeps them (apps.core.private_storage): on local disk under
// <root>/<namespace>/<name> in development, and as private DigitalOcean
// Spaces objects under <prefix>/private/<namespace>/<name> in production.
// The database holds generated basenames only, never a URL; a kept file is
// never overwritten.
package privatestore

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
)

var (
	// ErrExists is a name already kept: names are generated, so a second
	// write means a collision, never an update.
	ErrExists = errors.New("privatestore: the file already exists")
	// ErrNotFound is a name not kept.
	ErrNotFound = errors.New("privatestore: the file does not exist")
	// ErrBadName is a namespace or name that is not a generated one.
	ErrBadName = errors.New("privatestore: invalid file name")
)

// The existing module's own patterns (_STORED_NAME_RE, _NAMESPACE_RE).
var (
	storedName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
	namespace  = regexp.MustCompile(`^[a-z][a-z0-9_-]{0,63}$`)
)

// Store is where private files are kept.
type Store interface {
	Put(ctx context.Context, ns, name string, body []byte, contentType string) error
	Get(ctx context.Context, ns, name string) ([]byte, error)
	Delete(ctx context.Context, ns, name string) error
	// Provider is EvidenceRecord.storage_provider's word: local or spaces.
	Provider() string
}

func checkName(ns, name string) error {
	if !namespace.MatchString(ns) || !storedName.MatchString(name) {
		return ErrBadName
	}
	return nil
}

// Local keeps files on disk under root.
func Local(root string) Store { return localStore{root: root} }

type localStore struct{ root string }

func (l localStore) Provider() string { return "local" }

func (l localStore) path(ns, name string) (string, error) {
	if err := checkName(ns, name); err != nil {
		return "", err
	}
	return filepath.Join(l.root, ns, name), nil
}

func (l localStore) Put(_ context.Context, ns, name string, body []byte, _ string) error {
	path, err := l.path(ns, name)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return fmt.Errorf("privatestore: making the folder: %w", err)
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o640) // #nosec G304 -- generated name, checked above
	if errors.Is(err, fs.ErrExist) {
		return ErrExists
	}
	if err != nil {
		return fmt.Errorf("privatestore: creating the file: %w", err)
	}
	if _, err := file.Write(body); err != nil {
		_ = file.Close()
		_ = os.Remove(path)
		return fmt.Errorf("privatestore: writing the file: %w", err)
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return fmt.Errorf("privatestore: closing the file: %w", err)
	}
	return nil
}

func (l localStore) Get(_ context.Context, ns, name string) ([]byte, error) {
	path, err := l.path(ns, name)
	if err != nil {
		return nil, err
	}
	body, err := os.ReadFile(path) // #nosec G304 -- generated name, checked above
	if errors.Is(err, fs.ErrNotExist) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("privatestore: reading the file: %w", err)
	}
	return body, nil
}

func (l localStore) Delete(_ context.Context, ns, name string) error {
	path, err := l.path(ns, name)
	if err != nil {
		return err
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("privatestore: deleting the file: %w", err)
	}
	return nil
}

// FromEnv is the store the existing application's settings name: Spaces
// when SPACES_BUCKET_NAME is set, else local disk under root.
func FromEnv(getenv func(string) string, root string) Store {
	bucket := getenv("SPACES_BUCKET_NAME")
	if bucket == "" {
		return Local(root)
	}
	region := getenv("SPACES_REGION")
	endpoint := getenv("SPACES_ENDPOINT_URL")
	if endpoint == "" && region != "" {
		endpoint = "https://" + region + ".digitaloceanspaces.com"
	}
	prefix := getenv("SPACES_PREFIX")
	if prefix == "" {
		prefix = "edify"
	}
	return Spaces(SpacesConfig{
		Endpoint: endpoint, Region: region, Bucket: bucket, Prefix: prefix,
		AccessKey: getenv("SPACES_ACCESS_KEY_ID"), SecretKey: getenv("SPACES_SECRET_ACCESS_KEY"),
	}, nil, nil)
}
