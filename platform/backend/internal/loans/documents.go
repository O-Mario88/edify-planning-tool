package loans

import (
	"bytes"
	"path"
	"strings"
	"unicode"
)

// sniffDocument says what an uploaded file is from its first bytes, not its
// name: only PDFs, JPEGs and PNGs are kept as evidence.
func sniffDocument(content []byte) (string, error) {
	switch {
	case len(content) == 0:
		return "", need("file", "The file is empty.")
	case bytes.HasPrefix(content, []byte("%PDF-")):
		return "application/pdf", nil
	case bytes.HasPrefix(content, []byte{0xFF, 0xD8, 0xFF}):
		return "image/jpeg", nil
	case bytes.HasPrefix(content, []byte{0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A}):
		return "image/png", nil
	}
	return "", need("file", "Upload a PDF, JPEG or PNG file.")
}

// cleanFileName keeps a file's own name, without any path or control
// characters, and not too long.
func cleanFileName(name string) string {
	base := path.Base(strings.ReplaceAll(name, "\\", "/"))
	clean := strings.Map(func(r rune) rune {
		if unicode.IsControl(r) || r == '"' {
			return -1
		}
		return r
	}, base)
	if clean == "" || clean == "." || clean == "/" {
		clean = "document"
	}
	if len([]rune(clean)) > 120 {
		clean = string([]rune(clean)[:120])
	}
	return clean
}
