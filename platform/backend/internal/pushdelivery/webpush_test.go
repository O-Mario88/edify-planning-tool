package pushdelivery

import (
	"crypto/ecdh"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"math/big"
	"strings"
	"testing"
	"time"
)

//go:embed testdata/vectors.json
var vectorsJSON []byte

type vectors struct {
	ReceiverPrivate string         `json:"receiver_private"`
	P256dh          string         `json:"p256dh"`
	Auth            string         `json:"auth"`
	SenderPrivate   string         `json:"sender_private"`
	Salt            string         `json:"salt"`
	Plaintext       string         `json:"plaintext"`
	Record          string         `json:"record"`
	FCMMessage      map[string]any `json:"fcm_message"`
}

func readVectors(t *testing.T) vectors {
	t.Helper()
	var v vectors
	if err := json.Unmarshal(vectorsJSON, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

// The record is the existing webpush.encrypt's, with the same sender key and
// salt.
func TestEncryptIsTheExistingRecord(t *testing.T) {
	v := readVectors(t)
	raw, _ := hex.DecodeString(v.SenderPrivate)
	sender, err := ecdh.P256().NewPrivateKey(raw)
	if err != nil {
		t.Fatal(err)
	}
	salt, _ := unb64url(v.Salt)
	got, err := encrypt([]byte(v.Plaintext), v.P256dh, v.Auth, sender, salt)
	if err != nil {
		t.Fatal(err)
	}
	if b64url(got) != v.Record {
		t.Fatalf("record differs:\n got %s\nwant %s", b64url(got), v.Record)
	}
}

func TestPayloadIsWrittenAsTheExistingCodeWritesIt(t *testing.T) {
	v := readVectors(t)
	at := time.Date(2026, 11, 25, 3, 0, 0, 123456000, time.UTC)
	got, err := encodeJSON(payloadFor(notice{id: "n1", title: "Ação — 3 waiting", body: "Line <b>&</b> “quoted”",
		category: "verification", priority: "high", told: at}))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != v.Plaintext {
		t.Fatalf("payload differs:\n got %s\nwant %s", got, v.Plaintext)
	}
}

func TestVAPIDTokenNamesTheServiceAndVerifies(t *testing.T) {
	d := big.NewInt(0).SetBytes([]byte("0123456789abcdef0123456789abcdef"))
	x, y := elliptic.P256().ScalarBaseMult(d.Bytes())
	public := elliptic.Marshal(elliptic.P256(), x, y)
	c := WebConfig{PublicKey: b64url(public), PrivateKey: b64url(d.Bytes()), Subject: "mailto:ops@example.org"}
	header, err := c.vapidHeader("https://fcm.googleapis.com/fcm/send/abc", time.Unix(1_800_000_000, 0))
	if err != nil {
		t.Fatal(err)
	}
	token := strings.TrimSuffix(strings.TrimPrefix(header, "vapid t="), ", k="+c.PublicKey)
	parts := strings.Split(token, ".")
	if len(parts) != 3 || !strings.HasSuffix(header, ", k="+c.PublicKey) {
		t.Fatalf("header %q", header)
	}
	head, _ := unb64url(parts[0])
	claims, _ := unb64url(parts[1])
	if string(head) != `{"alg":"ES256","typ":"JWT"}` ||
		string(claims) != `{"aud":"https://fcm.googleapis.com","exp":1800043200,"sub":"mailto:ops@example.org"}` {
		t.Fatalf("token parts: %s %s", head, claims)
	}
	sig, _ := unb64url(parts[2])
	digest := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if !ecdsa.Verify(&ecdsa.PublicKey{Curve: elliptic.P256(), X: x, Y: y}, digest[:], new(big.Int).SetBytes(sig[:32]),
		new(big.Int).SetBytes(sig[32:])) {
		t.Fatal("the signature does not verify")
	}
}

func TestEndpointsAreTheBrowsersPushServices(t *testing.T) {
	for endpoint, want := range map[string]bool{
		"https://fcm.googleapis.com/fcm/send/x": true, "https://web.push.apple.com/abc": true,
		"http://fcm.googleapis.com/x": false, "https://evil.example.com/x": false, "https://u:p@fcm.googleapis.com/x": false,
	} {
		if got := allowedEndpoint(endpoint, nil); got != want {
			t.Errorf("%s: got %v", endpoint, got)
		}
	}
}

func TestFirebaseMessageIsTheExistingOne(t *testing.T) {
	v := readVectors(t)
	at := time.Date(2026, 11, 25, 3, 0, 0, 123456000, time.UTC)
	msg := fcmMessage("tok:abc", payloadFor(notice{id: "n1", title: "Ação — 3 waiting", body: "Line <b>&</b> “quoted”",
		category: "verification", priority: "high", told: at}), 24*time.Hour, true, "n1", at)
	msg["apns"].(map[string]any)["headers"].(map[string]any)["apns-expiration"] = "<exp>"
	got, _ := json.Marshal(msg)
	want, _ := json.Marshal(v.FCMMessage)
	if string(got) != string(want) {
		t.Fatalf("message differs:\n got %s\nwant %s", got, want)
	}
}
