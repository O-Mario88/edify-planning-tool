package evidence

import (
	"strings"
	"testing"
)

var (
	jpegHead = []byte("\xff\xd8\xff\xe0\x00\x10JFIF")
	pngHead  = []byte("\x89PNG\r\n\x1a\n\x00\x00")
	pdfHead  = []byte("%PDF-1.7\n")
	zipHead  = []byte("PK\x03\x04\x14\x00")
	oleHead  = []byte("\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00")
	webpHead = []byte("RIFF\x24\x00\x00\x00WEBPVP8 ")
)

// validation.assert_safe_upload, gate by gate, in its own words.
func TestAnUploadPassesEveryGateOrIsRefusedInTheExistingWords(t *testing.T) {
	tests := []struct {
		name, file, mime string
		head             []byte
		size             int64
		ext, refusal     string
	}{
		{"photo", "receipt.JPG", "image/jpeg", jpegHead, 100, ".jpg", ""},
		{"png", "a.png", "image/png", pngHead, 100, ".png", ""},
		{"webp", "a.webp", "image/webp", webpHead, 100, ".webp", ""},
		{"pdf generic type", "a.pdf", "application/octet-stream", pdfHead, 100, ".pdf", ""},
		{"docx", "a.docx", "", zipHead, 100, ".docx", ""},
		{"xls", "a.xls", "application/vnd.ms-excel", oleHead, 100, ".xls", ""},
		{"csv", "a.csv", "text/csv", []byte("school,score\n"), 100, ".csv", ""},
		{"too big", "a.pdf", "application/pdf", pdfHead, 10*1024*1024 + 1, "", "File exceeds the 10 MB limit."},
		{"blocked", "a.svg", "image/svg+xml", []byte("<svg"), 10, "", "File type '.svg' is not allowed."},
		{"heic", "IMG_1.HEIC", "image/heic", []byte("...."), 10, "", heicRefusal},
		{"unknown", "a.txt", "text/plain", []byte("hi"), 10, "", "File extension '.txt' is not allowed."},
		{"no extension", "receipt", "", jpegHead, 10, "", "File extension '(none)' is not allowed."},
		{"bad type", "a.pdf", "text/html", pdfHead, 10, "", "Declared content type 'text/html' is not allowed."},
		{"mismatch", "a.pdf", "image/png", pngHead, 10, "", "The file extension '.pdf' does not match its declared type 'image/png'."},
		{"sniff", "a.jpg", "image/jpeg", pdfHead, 10, "", "The file content does not match its declared type."},
		{"csv starting with a digit", "a.csv", "text/csv", []byte("1,2,3\n"), 10, "", "The file content does not match its declared type."},
	}
	for _, tt := range tests {
		ext, err := Check(tt.file, tt.mime, tt.head, tt.size)
		switch {
		case tt.refusal == "" && (err != nil || ext != tt.ext):
			t.Fatalf("%s: ext %q, err %v", tt.name, ext, err)
		case tt.refusal != "" && (err == nil || err.Error() != tt.refusal):
			t.Fatalf("%s: got %v, want %q", tt.name, err, tt.refusal)
		}
	}
}

// os.path.splitext: a name that is only a leading dot has no extension.
func TestTheExtensionIsReadAsPythonReadsIt(t *testing.T) {
	for name, want := range map[string]string{
		"a.tar.gz": ".gz", ".pdf": "", "dir/x.Pdf": ".pdf", "..x.jpg": ".jpg", "x.": ".", "noext": "",
	} {
		if got := extensionOf(name); got != want {
			t.Fatalf("%q = %q, want %q", name, got, want)
		}
	}
}

// infer_kind_from_upload: documents are "pdf", the rest the default.
func TestAnUploadsKindFollowsItsShape(t *testing.T) {
	for _, tt := range [][3]string{
		{"a.PDF", "", "pdf"}, {"a.docx", "", "pdf"}, {"x", "application/msword", "pdf"},
		{"a.jpg", "image/jpeg", "photo"}, {"a.xlsx", "", "photo"},
	} {
		if got := InferKind(tt[0], tt[1], "photo"); got != tt[2] {
			t.Fatalf("%v = %q", tt, got)
		}
	}
	if !strings.HasPrefix(heicRefusal, "HEIC photos") {
		t.Fatal("heic words")
	}
}
