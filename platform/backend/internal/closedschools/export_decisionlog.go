package closedschools

// PyInt is Python's int() of a query value (surrounding white space, a sign
// and underscores between digits allowed; a number too long to hold is the
// largest there is), for the Decision Log's lookback window.
func PyInt(text string) (int, bool) { return pyInt(text) }
