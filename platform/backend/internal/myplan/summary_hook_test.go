package myplan

// goldenSummary is the My Training Summary reader the golden comparisons
// give the service: internal/trainingsummary's, set by
// summary_reader_test.go (an outside test package may import it; this one
// may not, as it reads this package).
var goldenSummary TrainingSummaryReader

// SetGoldenSummary sets it.
func SetGoldenSummary(read TrainingSummaryReader) { goldenSummary = read }
