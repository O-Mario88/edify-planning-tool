// Package pushdelivery is the notification.push outbox handler
// (apps.notifications.push.handle_push) and the three services it sends
// through: Web Push to a browser (RFC 8291 aes128gcm, VAPID RFC 8292;
// apps.notifications.webpush), Apple's own push to an iPhone that gave an
// APNs token (apps.notifications.apns), and Firebase to the app on Android or
// an iPhone that gave a Firebase token (apps.notifications.fcm).
package pushdelivery

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/hkdf"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// The outcomes a send ends in (webpush.PushGone, PushRejected,
// PushUnavailable).
var (
	ErrGone        = errors.New("push: the device is gone")
	ErrRejected    = errors.New("push: refused for good")
	ErrUnavailable = errors.New("push: the service could not take it now")
)

// failure is one outcome with the service's words.
type failure struct {
	kind   error
	detail string
}

func (f *failure) Error() string { return f.detail }
func (f *failure) Unwrap() error { return f.kind }

func gone(detail string) error        { return &failure{ErrGone, detail} }
func rejected(detail string) error    { return &failure{ErrRejected, detail} }
func unavailable(detail string) error { return &failure{ErrUnavailable, detail} }

// pushServiceHosts are PUSH_SERVICE_HOSTS.
var pushServiceHosts = []string{"fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com",
	"push.services.mozilla.com", "push.apple.com", "notify.windows.com"}

const (
	recordSize    = 4096
	maxPlaintext  = 3900
	vapidLifetime = 12 * time.Hour
)

func b64url(data []byte) string { return base64.RawURLEncoding.EncodeToString(data) }

func unb64url(text string) ([]byte, error) {
	return base64.RawURLEncoding.DecodeString(strings.TrimRight(strings.TrimSpace(text), "="))
}

// allowedEndpoint is allowed_endpoint: an https address on a browser's push
// service.
func allowedEndpoint(endpoint string, extra []string) bool {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "https" || u.User != nil {
		return false
	}
	host := strings.ToLower(u.Hostname())
	if host == "" {
		return false
	}
	for _, allowed := range append(append([]string{}, pushServiceHosts...), extra...) {
		if host == allowed || strings.HasSuffix(host, "."+allowed) {
			return true
		}
	}
	return false
}

// WebConfig is this deployment's VAPID key pair and subject.
type WebConfig struct {
	PublicKey, PrivateKey, Subject string
	ExtraHosts                     []string
}

func (c WebConfig) configured() bool {
	return strings.TrimSpace(c.PublicKey) != "" && strings.TrimSpace(c.PrivateKey) != ""
}

func (c WebConfig) signingKey() (*ecdsa.PrivateKey, error) {
	raw, err := unb64url(c.PrivateKey)
	if err != nil {
		return nil, fmt.Errorf("push: the VAPID private key is not base64url: %w", err)
	}
	d := new(big.Int).SetBytes(raw)
	key := &ecdsa.PrivateKey{D: d, PublicKey: ecdsa.PublicKey{Curve: elliptic.P256()}}
	key.PublicKey.X, key.PublicKey.Y = elliptic.P256().ScalarBaseMult(raw)
	return key, nil
}

// vapidHeader is _vapid_header: a token naming the push service it is for,
// expiring in twelve hours, and the public key.
func (c WebConfig) vapidHeader(endpoint string, now time.Time) (string, error) {
	u, err := url.Parse(endpoint)
	if err != nil {
		return "", err
	}
	key, err := c.signingKey()
	if err != nil {
		return "", err
	}
	subject := c.Subject
	if subject == "" {
		subject = "mailto:admin@edify.org"
	}
	token, err := es256(key, map[string]any{"typ": "JWT", "alg": "ES256"}, []jwtField{
		{"aud", u.Scheme + "://" + u.Host}, {"exp", now.Add(vapidLifetime).Unix()}, {"sub", subject},
	})
	if err != nil {
		return "", err
	}
	return "vapid t=" + token + ", k=" + strings.TrimSpace(c.PublicKey), nil
}

func hkdfKey(length int, salt, info, secret []byte) ([]byte, error) {
	return hkdf.Key(sha256.New, secret, salt, string(info), length)
}

// encrypt is webpush.encrypt: one aes128gcm record with its header, to the
// subscription's keys. sender and salt are fresh for every message; a test
// passes them.
func encrypt(plaintext []byte, p256dh, auth string, sender *ecdh.PrivateKey, salt []byte) ([]byte, error) {
	if len(plaintext) > maxPlaintext {
		return nil, errors.New("push: a payload must fit one record")
	}
	receiverPublic, err := unb64url(p256dh)
	if err != nil {
		return nil, fmt.Errorf("push: the subscription's key is not base64url: %w", err)
	}
	secret, err := unb64url(auth)
	if err != nil {
		return nil, fmt.Errorf("push: the subscription's secret is not base64url: %w", err)
	}
	receiver, err := ecdh.P256().NewPublicKey(receiverPublic)
	if err != nil {
		return nil, fmt.Errorf("push: the subscription's key is not a P-256 point: %w", err)
	}
	if sender == nil {
		if sender, err = ecdh.P256().GenerateKey(rand.Reader); err != nil {
			return nil, err
		}
	}
	if salt == nil {
		salt = make([]byte, 16)
		if _, err := rand.Read(salt); err != nil {
			return nil, err
		}
	}
	senderPublic := sender.PublicKey().Bytes()
	shared, err := sender.ECDH(receiver)
	if err != nil {
		return nil, err
	}
	info := append(append([]byte("WebPush: info\x00"), receiverPublic...), senderPublic...)
	ikm, err := hkdfKey(32, secret, info, shared)
	if err != nil {
		return nil, err
	}
	key, err := hkdfKey(16, salt, []byte("Content-Encoding: aes128gcm\x00"), ikm)
	if err != nil {
		return nil, err
	}
	nonce, err := hkdfKey(12, salt, []byte("Content-Encoding: nonce\x00"), ikm)
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	sealed := gcm.Seal(nil, nonce, append(append([]byte{}, plaintext...), 0x02), nil)
	var header bytes.Buffer
	header.Write(salt)
	_ = binary.Write(&header, binary.BigEndian, uint32(recordSize))
	header.WriteByte(byte(len(senderPublic)))
	header.Write(senderPublic)
	return append(header.Bytes(), sealed...), nil
}

// Web is Web Push with the deployment's VAPID keys.
type Web struct {
	Config WebConfig
	client *http.Client
}

// NewWeb is the browser sender; nil when the key pair is missing.
func NewWeb(c WebConfig, client *http.Client) *Web {
	if !c.configured() {
		return nil
	}
	return &Web{Config: c, client: client}
}

// Send is webpush.send: the payload encrypted and posted to the
// subscription's push service.
func (w *Web) Send(ctx context.Context, endpoint, p256dh, auth string, payload orderedObject, ttl time.Duration,
	urgency, topic string, now time.Time) error {
	if !allowedEndpoint(endpoint, w.Config.ExtraHosts) {
		return rejected("The endpoint is not a browser push service.")
	}
	plain, err := encodeJSON(payload)
	if err != nil {
		return err
	}
	body, err := encrypt(plain, p256dh, auth, nil, nil)
	if err != nil {
		return rejected(err.Error())
	}
	authorization, err := w.Config.vapidHeader(endpoint, now)
	if err != nil {
		return rejected(err.Error())
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return rejected(err.Error())
	}
	switch urgency {
	case "very-low", "low", "normal", "high":
	default:
		urgency = "normal"
	}
	req.Header.Set("Authorization", authorization)
	req.Header.Set("Content-Encoding", "aes128gcm")
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("TTL", strconv.FormatInt(int64(ttl/time.Second), 10))
	req.Header.Set("Urgency", urgency)
	if topic != "" {
		if len(topic) > 32 {
			topic = topic[:32]
		}
		req.Header.Set("Topic", topic)
	}
	resp, err := w.client.Do(req)
	if err != nil {
		return unavailable(fmt.Sprintf("%T: %v", err, err))
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case 200, 201, 202, 204:
		return nil
	}
	text, _ := io.ReadAll(io.LimitReader(resp.Body, 200))
	detail := strings.TrimSpace(fmt.Sprintf("%d %s", resp.StatusCode, text))
	switch {
	case resp.StatusCode == 404 || resp.StatusCode == 410:
		return gone(detail)
	case resp.StatusCode == 429 || resp.StatusCode >= 500:
		return unavailable(detail)
	}
	return rejected(detail)
}
