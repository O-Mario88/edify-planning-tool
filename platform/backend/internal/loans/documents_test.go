package loans

import "testing"

func TestOnlyRealPDFsAndImagesAreKept(t *testing.T) {
	for content, want := range map[string]string{
		"%PDF-1.7\n...":              "application/pdf",
		"\xFF\xD8\xFF\xE0jpeg":       "image/jpeg",
		"\x89PNG\x0D\x0A\x1A\x0Apng": "image/png",
	} {
		if got, err := sniffDocument([]byte(content)); err != nil || got != want {
			t.Errorf("sniff(%q) = %q, %v", content[:4], got, err)
		}
	}
	for _, content := range []string{"", "<html>pdf</html>", "PK\x03\x04 a zip renamed .pdf", "MZ an exe"} {
		if _, err := sniffDocument([]byte(content)); err == nil {
			t.Errorf("sniff accepted %q", content)
		}
	}
}

func TestFileNamesLoseTheirPaths(t *testing.T) {
	for raw, want := range map[string]string{
		"../../etc/passwd": "passwd", `C:\temp\receipt.pdf`: "receipt.pdf", "receipt\n.pdf": "receipt.pdf", "": "document",
	} {
		if got := cleanFileName(raw); got != want {
			t.Errorf("cleanFileName(%q) = %q, want %q", raw, got, want)
		}
	}
}
