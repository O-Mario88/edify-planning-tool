package todos

import (
	"context"
	"errors"
	"testing"
)

func TestCollectPassesOnWhenABuilderFails(t *testing.T) {
	saved := map[string]func(context.Context, *Service, *reader) ([]todo, error){}
	for k, v := range Handled {
		saved[k] = v
	}
	t.Cleanup(func() {
		for k := range Handled {
			delete(Handled, k)
		}
		for k, v := range saved {
			Handled[k] = v
		}
	})
	Handled["test_ok"] = func(context.Context, *Service, *reader) ([]todo, error) { return []todo{{}}, nil }
	Handled["test_fails"] = func(context.Context, *Service, *reader) ([]todo, error) { return nil, errors.New("boom") }
	Handled["test_pass_on"] = func(context.Context, *Service, *reader) ([]todo, error) { return nil, errPassOn }

	cases := []struct {
		name       string
		builders   []string
		cancelled  bool
		wantServed bool
		wantErr    bool
		wantRows   int
	}{
		{"all builders answer", []string{"test_ok", "test_ok"}, false, true, false, 2},
		{"a failing builder passes the reader on", []string{"test_ok", "test_fails"}, false, false, false, 0},
		{"a builder Go lacks passes the reader on", []string{"test_pass_on"}, false, false, false, 0},
		{"a cancelled request is still an error", []string{"test_fails"}, true, true, true, 0},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			if c.cancelled {
				cancel()
			} else {
				defer cancel()
			}
			rows, served, err := collect(ctx, nil, &reader{}, c.builders)
			if served != c.wantServed || (err != nil) != c.wantErr || len(rows) != c.wantRows {
				t.Fatalf("got rows=%d served=%v err=%v; want rows=%d served=%v err=%v", len(rows), served, err, c.wantRows, c.wantServed, c.wantErr)
			}
		})
	}
}
