package evidence

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"net"
	"strconv"
	"strings"
	"time"
)

// Scanner is _scan_upload's ClamAV daemon. An empty Host is no scanner:
// every file is "skipped", as it is with CLAMAV_HOST unset.
type Scanner struct {
	Host    string
	Port    int
	Timeout time.Duration
}

// ScannerFromEnv reads CLAMAV_HOST, CLAMAV_PORT and CLAMAV_TIMEOUT_SECONDS.
func ScannerFromEnv(getenv func(string) string) Scanner {
	port, err := strconv.Atoi(getenv("CLAMAV_PORT"))
	if err != nil || port <= 0 {
		port = 3310
	}
	seconds, err := strconv.Atoi(getenv("CLAMAV_TIMEOUT_SECONDS"))
	if err != nil || seconds <= 0 {
		seconds = 10
	}
	return Scanner{Host: getenv("CLAMAV_HOST"), Port: port, Timeout: time.Duration(seconds) * time.Second}
}

const scanChunk = 64 * 1024

// Scan answers clean, infected (with the threat's name) or skipped. A scan
// never blocks an upload: any scanner problem is "skipped".
func (s Scanner) Scan(body []byte) (status, threat string) {
	if s.Host == "" {
		return "skipped", ""
	}
	reply, err := s.instream(body)
	if err != nil {
		return "skipped", ""
	}
	reply = strings.TrimSpace(strings.TrimRight(reply, "\x00"))
	reply = strings.TrimPrefix(reply, "stream:")
	reply = strings.TrimSpace(reply)
	switch {
	case reply == "OK":
		return "clean", ""
	case strings.HasSuffix(reply, " FOUND"):
		return "infected", strings.TrimSuffix(reply, " FOUND")
	}
	return "skipped", ""
}

func (s Scanner) instream(body []byte) (string, error) {
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(s.Host, strconv.Itoa(s.Port)), s.Timeout)
	if err != nil {
		return "", err
	}
	defer func() { _ = conn.Close() }()
	if err := conn.SetDeadline(time.Now().Add(s.Timeout)); err != nil {
		return "", err
	}
	if _, err := conn.Write([]byte("zINSTREAM\x00")); err != nil {
		return "", err
	}
	size := make([]byte, 4)
	for start := 0; start < len(body); start += scanChunk {
		end := min(start+scanChunk, len(body))
		binary.BigEndian.PutUint32(size, uint32(end-start)) // #nosec G115 -- a chunk is at most 64 KiB
		if _, err := conn.Write(size); err != nil {
			return "", err
		}
		if _, err := conn.Write(body[start:end]); err != nil {
			return "", err
		}
	}
	if _, err := conn.Write([]byte{0, 0, 0, 0}); err != nil {
		return "", err
	}
	reply, err := bufio.NewReader(conn).ReadString(0)
	if err != nil && reply == "" {
		return "", fmt.Errorf("evidence: reading the scanner's answer: %w", err)
	}
	return reply, nil
}
