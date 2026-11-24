package evidence

import (
	"bufio"
	"encoding/binary"
	"io"
	"net"
	"strconv"
	"testing"
	"time"
)

// fakeClamd answers one INSTREAM with reply, after reading every chunk.
func fakeClamd(t *testing.T, reply string) (string, int, *[]byte) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	got := []byte{}
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()
		r := bufio.NewReader(conn)
		if cmd, _ := r.ReadString(0); cmd != "zINSTREAM\x00" {
			return
		}
		size := make([]byte, 4)
		for {
			if _, err := io.ReadFull(r, size); err != nil {
				return
			}
			n := binary.BigEndian.Uint32(size)
			if n == 0 {
				break
			}
			chunk := make([]byte, n)
			if _, err := io.ReadFull(r, chunk); err != nil {
				return
			}
			got = append(got, chunk...)
		}
		_, _ = conn.Write([]byte(reply))
	}()
	host, port, _ := net.SplitHostPort(ln.Addr().String())
	p, _ := strconv.Atoi(port)
	return host, p, &got
}

func TestNoScannerMeansSkipped(t *testing.T) {
	if status, _ := (Scanner{}).Scan([]byte("x")); status != "skipped" {
		t.Fatalf("status %q", status)
	}
}

func TestACleanFileIsClean(t *testing.T) {
	host, port, got := fakeClamd(t, "stream: OK\x00")
	status, threat := Scanner{Host: host, Port: port, Timeout: 2 * time.Second}.Scan([]byte("hello file"))
	if status != "clean" || threat != "" {
		t.Fatalf("status %q threat %q", status, threat)
	}
	time.Sleep(10 * time.Millisecond)
	if string(*got) != "hello file" {
		t.Fatalf("scanner read %q", *got)
	}
}

func TestAnInfectedFileNamesItsThreat(t *testing.T) {
	host, port, _ := fakeClamd(t, "stream: Eicar-Test-Signature FOUND\x00")
	status, threat := Scanner{Host: host, Port: port, Timeout: 2 * time.Second}.Scan([]byte("X5O!P%@AP"))
	if status != "infected" || threat != "Eicar-Test-Signature" {
		t.Fatalf("status %q threat %q", status, threat)
	}
}

func TestAScannerThatCannotBeReachedSkips(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	_, port, _ := net.SplitHostPort(ln.Addr().String())
	_ = ln.Close()
	p, _ := strconv.Atoi(port)
	if status, _ := (Scanner{Host: "127.0.0.1", Port: p, Timeout: time.Second}).Scan([]byte("x")); status != "skipped" {
		t.Fatalf("status %q", status)
	}
}
