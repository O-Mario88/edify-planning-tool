package todos

import (
	"context"
	"testing"
)

func TestRegisterRefusesASecondBuilderOfTheSameName(t *testing.T) {
	const name = "test.only:duplicate_probe"
	t.Cleanup(func() { delete(Handled, name) })
	build := func(context.Context, *Service, *reader) ([]todo, error) { return nil, nil }

	register(name, build)
	defer func() {
		if recover() == nil {
			t.Fatal("a second registration of the same builder was accepted")
		}
	}()
	register(name, build)
}
