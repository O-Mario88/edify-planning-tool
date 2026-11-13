package staffactivity

// PagePath is presence_labels.page_path, for internal/presence (the beat Go
// stamps for the requests it answers, docs/migration/65).
func PagePath(value string) string { return pagePath(value) }

// SectionFor is presence_labels.section_for, for internal/presence.
func SectionFor(path string) string { return sectionFor(path) }
