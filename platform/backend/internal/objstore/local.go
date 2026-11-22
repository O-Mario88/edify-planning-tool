package objstore

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// LocalStore stores objects under a single root directory on local disk.
type LocalStore struct {
	root string
}

// NewLocal creates a LocalStore rooted at dir.
func NewLocal(dir string) (*LocalStore, error) {
	abs, err := filepath.Abs(strings.TrimSpace(dir))
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(abs, 0o750); err != nil {
		return nil, err
	}
	return &LocalStore{root: abs}, nil
}

func (l *LocalStore) Backend() string { return "local" }

func (l *LocalStore) pathOf(key string) (string, string, error) {
	clean, err := CleanKey(key)
	if err != nil {
		return "", "", err
	}
	full := filepath.Join(l.root, filepath.FromSlash(clean))
	rel, err := filepath.Rel(l.root, full)
	if err != nil || strings.HasPrefix(rel, "..") {
		return "", "", ErrInvalidKey
	}
	return clean, full, nil
}

func (l *LocalStore) Put(_ context.Context, key, contentType string, body io.Reader) (ObjectMeta, error) {
	clean, full, err := l.pathOf(key)
	if err != nil {
		return ObjectMeta{}, err
	}
	if err := os.MkdirAll(filepath.Dir(full), 0o750); err != nil {
		return ObjectMeta{}, err
	}
	data, err := io.ReadAll(body)
	if err != nil {
		return ObjectMeta{}, err
	}
	tmp := full + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return ObjectMeta{}, err
	}
	if err := os.Rename(tmp, full); err != nil {
		_ = os.Remove(tmp)
		return ObjectMeta{}, err
	}
	return ObjectMeta{Key: clean, Size: int64(len(data)), ContentType: contentType}, nil
}

func (l *LocalStore) Get(_ context.Context, key string) (io.ReadCloser, ObjectMeta, error) {
	clean, full, err := l.pathOf(key)
	if err != nil {
		return nil, ObjectMeta{}, err
	}
	f, err := os.Open(full)
	if errors.Is(err, os.ErrNotExist) {
		return nil, ObjectMeta{}, ErrNotFound
	}
	if err != nil {
		return nil, ObjectMeta{}, err
	}
	info, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return nil, ObjectMeta{}, err
	}
	return f, ObjectMeta{Key: clean, Size: info.Size()}, nil
}

func (l *LocalStore) Delete(_ context.Context, key string) error {
	_, full, err := l.pathOf(key)
	if err != nil {
		return err
	}
	if err := os.Remove(full); err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("objstore: delete %s: %w", key, err)
	}
	return nil
}
