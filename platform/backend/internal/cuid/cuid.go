// Package cuid issues ids in the existing application's CUID format
// (apps/core/cuid.py): "c", the base-36 millisecond time, a two-character
// counter, four random characters, a four-character process fingerprint and
// two more random characters. Rows Go adds to the existing tables (audit
// entries, refresh tokens, sign-in codes) carry ids of the same shape as the
// existing ones. No existing id is ever re-issued: every id is new.
package cuid

import (
	"crypto/rand"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"

var (
	mu          sync.Mutex
	counter     int64
	lastMillis  int64
	fingerprint = processFingerprint()
)

// New returns a fresh id.
func New() string {
	now := time.Now().UnixMilli()
	mu.Lock()
	if now == lastMillis {
		counter++
	} else {
		counter, lastMillis = 0, now
	}
	local := counter
	mu.Unlock()

	count := strconv.FormatInt(local, 36)
	if len(count) < 2 {
		count = strings.Repeat("0", 2-len(count)) + count
	}
	return "c" + strconv.FormatInt(now, 36) + count[:2] + randomBlock(4) + fingerprint + randomBlock(2)
}

func randomBlock(size int) string {
	raw := make([]byte, size)
	if _, err := rand.Read(raw); err != nil {
		// crypto/rand does not fail on supported platforms; an id must never
		// be issued without its random part.
		panic(fmt.Sprintf("cuid: reading randomness: %v", err))
	}
	out := make([]byte, size)
	for i, b := range raw {
		out[i] = alphabet[int(b)%len(alphabet)]
	}
	return string(out)
}

func processFingerprint() string {
	source := strconv.Itoa(os.Getpid()) + randomBlock(6)
	var out strings.Builder
	for _, ch := range source {
		out.WriteString(strconv.FormatInt(int64(ch)%36, 36))
	}
	mark := out.String()
	if len(mark) >= 4 {
		return mark[:4]
	}
	return mark + strings.Repeat("0", 4-len(mark))
}
