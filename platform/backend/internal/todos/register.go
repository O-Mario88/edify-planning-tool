package todos

import (
	"context"
	"fmt"
)

// register adds a builder Go answers for. Each file registers its own
// builders at start-up, and a plain map assignment let a second file
// silently replace the first (four builders were doubled by one merge,
// docs/migration/56–58). A second registration of a name is a programming
// error, so it stops the program at start-up.
func register(name string, build func(context.Context, *Service, *reader) ([]todo, error)) {
	if _, taken := Handled[name]; taken {
		panic(fmt.Sprintf("todos: builder %q is registered twice", name))
	}
	Handled[name] = build
}
