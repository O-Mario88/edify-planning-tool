package pushdelivery

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/elliptic"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// decrypt is the browser's side of RFC 8291, to read what was sent.
func decrypt(t *testing.T, record []byte, receiver *ecdh.PrivateKey, authSecret []byte) []byte {
	t.Helper()
	salt, keyLen := record[:16], int(record[20])
	if binary.BigEndian.Uint32(record[16:20]) != recordSize {
		t.Fatal("record size")
	}
	senderPublic := record[21 : 21+keyLen]
	sender, err := ecdh.P256().NewPublicKey(senderPublic)
	if err != nil {
		t.Fatal(err)
	}
	shared, _ := receiver.ECDH(sender)
	info := append(append([]byte("WebPush: info\x00"), receiver.PublicKey().Bytes()...), senderPublic...)
	ikm, _ := hkdfKey(32, authSecret, info, shared)
	key, _ := hkdfKey(16, salt, []byte("Content-Encoding: aes128gcm\x00"), ikm)
	nonce, _ := hkdfKey(12, salt, []byte("Content-Encoding: nonce\x00"), ikm)
	block, _ := aes.NewCipher(key)
	gcm, _ := cipher.NewGCM(block)
	plain, err := gcm.Open(nil, nonce, record[21+keyLen:], nil)
	if err != nil {
		t.Fatal(err)
	}
	return plain[:len(plain)-1] // the 0x02 delimiter
}

func TestWebSendPostsWhatTheExistingSenderPosts(t *testing.T) {
	v := readVectors(t)
	raw, _ := hex.DecodeString(v.ReceiverPrivate)
	receiver, _ := ecdh.P256().NewPrivateKey(raw)
	secret, _ := unb64url(v.Auth)
	var got *http.Request
	var body []byte
	status := http.StatusCreated
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got, body = r, func() []byte { b, _ := io.ReadAll(r.Body); return b }()
		w.WriteHeader(status)
	}))
	defer server.Close()
	d := big.NewInt(0).SetBytes([]byte("0123456789abcdef0123456789abcdef"))
	x, y := elliptic.P256().ScalarBaseMult(d.Bytes())
	web := &Web{Config: WebConfig{PublicKey: b64url(elliptic.Marshal(elliptic.P256(), x, y)), PrivateKey: b64url(d.Bytes()),
		Subject: "mailto:ops@example.org", ExtraHosts: []string{"127.0.0.1"}}, client: server.Client()}
	payload := payloadFor(notice{id: "n1", title: "T", body: "B", category: "c", priority: "high", told: time.Now()})
	if err := web.Send(context.Background(), server.URL+"/push/abc", v.P256dh, v.Auth, payload, 24*time.Hour, "high",
		"cmwvtopicidthatisverylongerthanthirtytwo", time.Now()); err != nil {
		t.Fatal(err)
	}
	want, _ := encodeJSON(payload)
	if plain := decrypt(t, body, receiver, secret); string(plain) != string(want) {
		t.Fatalf("decrypted %s, want %s", plain, want)
	}
	for header, wantValue := range map[string]string{"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
		"Ttl": "86400", "Urgency": "high", "Topic": "cmwvtopicidthatisverylongerthant"} {
		if got.Header.Get(header) != wantValue {
			t.Errorf("%s = %q, want %q", header, got.Header.Get(header), wantValue)
		}
	}
	if !strings.HasPrefix(got.Header.Get("Authorization"), "vapid t=") {
		t.Errorf("authorization %q", got.Header.Get("Authorization"))
	}
	for code, want := range map[int]error{201: nil, 204: nil, 404: ErrGone, 410: ErrGone, 429: ErrUnavailable, 503: ErrUnavailable,
		400: ErrRejected, 413: ErrRejected} {
		status = code
		err := web.Send(context.Background(), server.URL+"/push/abc", v.P256dh, v.Auth, payload, time.Hour, "normal", "", time.Now())
		if (want == nil) != (err == nil) || (want != nil && !errors.Is(err, want)) {
			t.Errorf("status %d: got %v, want %v", code, err, want)
		}
	}
	if err := web.Send(context.Background(), "https://evil.example.com/x", v.P256dh, v.Auth, payload, time.Hour, "normal", "",
		time.Now()); !errors.Is(err, ErrRejected) {
		t.Errorf("a stranger's endpoint: %v", err)
	}
}

func TestFirebaseFailuresAreTheExistingOutcomes(t *testing.T) {
	f := &FCM{held: map[[2]string]heldToken{}, account: &serviceAccount{}}
	cases := []struct {
		status int
		body   map[string]any
		want   error
	}{
		{404, nil, ErrGone},
		{400, map[string]any{"error": map[string]any{"message": "The registration token is not a valid FCM registration token"}}, ErrGone},
		{403, map[string]any{"error": map[string]any{"details": []any{map[string]any{"errorCode": "SENDER_ID_MISMATCH"}}}}, ErrGone},
		{401, nil, ErrUnavailable},
		{500, nil, ErrUnavailable},
		{400, map[string]any{"error": map[string]any{"details": []any{map[string]any{"errorCode": "QUOTA_EXCEEDED"}}}}, ErrUnavailable},
		{401, map[string]any{"error": map[string]any{"details": []any{map[string]any{"errorCode": "THIRD_PARTY_AUTH_ERROR"}}}}, ErrRejected},
		{400, map[string]any{"error": map[string]any{"message": "bad payload"}}, ErrRejected},
	}
	for _, c := range cases {
		if err := f.failureOf(c.status, c.body); !errors.Is(err, c.want) {
			t.Errorf("%d %v: got %v, want %v", c.status, c.body, err, c.want)
		}
	}
	for token, want := range map[string]bool{"abc:" + strings.Repeat("x", 40): true, strings.Repeat("a", 64): false, "short:x": false} {
		if validFCMToken(token) != want {
			t.Errorf("token %q", token)
		}
	}
}
