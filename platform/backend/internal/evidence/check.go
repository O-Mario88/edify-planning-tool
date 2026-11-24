// Package evidence takes files people upload as activity evidence, as the
// existing application does (apps.evidence.services.record_upload and
// apps.evidence.validation): every upload passes the same five gates, is kept
// in private storage under a generated name, is scanned when a scanner is
// configured, and is recorded against its activity.
package evidence

import (
	"bytes"
	"fmt"
	"strings"
	"unicode/utf8"
)

// MaxFileSize is validation.MAX_FILE_SIZE.
const MaxFileSize = 10 * 1024 * 1024

// Refusal is an upload the existing gates refuse, in their words.
type Refusal struct{ Message string }

func (r *Refusal) Error() string { return r.Message }

func refuse(format string, args ...any) error { return &Refusal{Message: fmt.Sprintf(format, args...)} }

// heicRefusal is validation.HEIC_REFUSAL.
const heicRefusal = "HEIC photos (the iPhone's own format) cannot be opened here. Save the " +
	"photo as JPEG, or take it again with the camera, and upload that."

var (
	allowedMIME = map[string]bool{
		"image/jpeg": true, "image/png": true, "image/webp": true, "application/pdf": true,
		"application/msword": true,
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document": true,
		"application/vnd.ms-excel": true,
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": true,
		"text/csv": true, "application/octet-stream": true,
	}
	extensionFamily = map[string]string{
		".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp", ".pdf": "pdf",
		".doc": "ole", ".docx": "zip", ".xls": "ole", ".xlsx": "zip", ".csv": "text",
	}
	blocked = map[string]bool{
		".svg": true, ".html": true, ".htm": true, ".xhtml": true, ".xml": true, ".js": true, ".mjs": true,
		".exe": true, ".bat": true, ".cmd": true, ".sh": true, ".php": true, ".py": true, ".jar": true,
		".zip": true, ".tar": true, ".gz": true, ".7z": true, ".rar": true,
	}
	heic       = map[string]bool{".heic": true, ".heif": true}
	mimeToExts = map[string][]string{
		"image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}, "image/webp": {".webp"},
		"application/pdf": {".pdf"}, "application/msword": {".doc"},
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
		"application/vnd.ms-excel": {".xls"},
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
		"text/csv": {".csv"}, "application/vnd.ms-powerpoint": {".ppt"},
		"application/vnd.openxmlformats-officedocument.presentationml.presentation": {".pptx"},
	}
	signatures = map[string][][]byte{
		"jpeg": {[]byte("\xff\xd8\xff")},
		"png":  {[]byte("\x89PNG\r\n\x1a\n")},
		"pdf":  {[]byte("%PDF")},
		"zip":  {[]byte("PK\x03\x04"), []byte("PK\x05\x06"), []byte("PK\x07\x08")},
		"ole":  {[]byte("\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")},
	}
)

// extensionOf is os.path.splitext(name)[1].lower() on a posix path.
func extensionOf(name string) string {
	base := name[strings.LastIndex(name, "/")+1:]
	trimmed := strings.TrimLeft(base, ".")
	i := strings.LastIndex(trimmed, ".")
	if i < 0 {
		return ""
	}
	return strings.ToLower(trimmed[i:])
}

// families is _detect_families: what the first bytes are.
func families(head []byte) map[string]bool {
	if len(head) > 512 {
		head = head[:512]
	}
	found := map[string]bool{}
	for family, sigs := range signatures {
		for _, sig := range sigs {
			if bytes.HasPrefix(head, sig) {
				found[family] = true
				break
			}
		}
	}
	if len(head) >= 12 && string(head[:4]) == "RIFF" && string(head[8:12]) == "WEBP" {
		found["webp"] = true
	}
	if len(found) == 0 {
		first := head
		if len(first) > 64 {
			first = first[:64]
		}
		startsWithDigit := len(head) > 0 && head[0] >= '0' && head[0] <= '9'
		if len(bytes.Trim(first, "\x00")) > 0 && !startsWithDigit && isASCII(first) {
			found["text"] = true
		}
	}
	return found
}

func isASCII(b []byte) bool {
	for _, c := range b {
		if c >= utf8.RuneSelf {
			return false
		}
	}
	return true
}

// Check is assert_safe_upload: the normalized extension, or the refusal.
func Check(name, mime string, head []byte, size int64) (string, error) {
	if size > MaxFileSize {
		return "", refuse("File exceeds the %d MB limit.", MaxFileSize/(1024*1024))
	}
	ext := extensionOf(name)
	if blocked[ext] {
		return "", refuse("File type '%s' is not allowed.", ext)
	}
	family, known := extensionFamily[ext]
	if heic[ext] && !known {
		return "", refuse("%s", heicRefusal)
	}
	if !known {
		shown := ext
		if shown == "" {
			shown = "(none)"
		}
		return "", refuse("File extension '%s' is not allowed.", shown)
	}
	if mime != "" && !allowedMIME[mime] {
		return "", refuse("Declared content type '%s' is not allowed.", mime)
	}
	if mime != "" && mime != "application/octet-stream" {
		if exts, ok := mimeToExts[mime]; ok && !contains(exts, ext) {
			return "", refuse("The file extension '%s' does not match its declared type '%s'.", ext, mime)
		}
	}
	if !families(head)[family] {
		return "", refuse("The file content does not match its declared type.")
	}
	return ext, nil
}

func contains(list []string, v string) bool {
	for _, item := range list {
		if item == v {
			return true
		}
	}
	return false
}

// InferKind is infer_kind_from_upload: a PDF or Word document is "pdf";
// anything else is the caller's default.
func InferKind(name, mime, fallback string) string {
	lower := strings.ToLower(name)
	switch {
	case strings.HasSuffix(lower, ".pdf"), strings.HasSuffix(lower, ".doc"), strings.HasSuffix(lower, ".docx"):
		return "pdf"
	}
	switch strings.ToLower(mime) {
	case "application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
		return "pdf"
	}
	return fallback
}
