package clusterpage

// PyInt is Python's int() of a query value (surrounding whitespace, a sign
// and underscores between digits allowed), for the pages beside this one
// that read a page number the same way.
func PyInt(text string) (int, bool) { return pyInt(text) }
