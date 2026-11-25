package pushdelivery

import (
	"context"
	"crypto/ecdsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

var apnsHosts = map[string]string{"production": "https://api.push.apple.com", "development": "https://api.sandbox.push.apple.com"}

const apnsTokenLifetime = 50 * time.Minute

var (
	apnsGoneReasons = map[string]bool{"BadDeviceToken": true, "Unregistered": true, "DeviceTokenNotForTopic": true}
	apnsToken       = regexp.MustCompile(`^[0-9a-fA-F]{64,200}$`)
)

// validAPNsToken is apns.valid_token: the raw token iOS gives an app.
func validAPNsToken(token string) bool { return apnsToken.MatchString(token) }

// APNs sends to Apple directly with the deployment's key.
type APNs struct {
	KeyID, TeamID, PrivateKey, Topic, Environment string
	client                                        *http.Client
	mu                                            sync.Mutex
	token                                         string
	signedAt                                      time.Time
	host                                          string
}

// NewAPNs is Apple's sender; nil when the key, team or key id is missing.
func NewAPNs(keyID, teamID, privateKey, topic, environment string, client *http.Client) *APNs {
	if keyID == "" || teamID == "" || privateKey == "" {
		return nil
	}
	host, ok := apnsHosts[environment]
	if !ok {
		host = apnsHosts["production"]
	}
	return &APNs{KeyID: keyID, TeamID: teamID, PrivateKey: privateKey, Topic: topic, Environment: environment,
		client: client, host: host}
}

func (a *APNs) forget() {
	a.mu.Lock()
	a.token = ""
	a.mu.Unlock()
}

// signature is apns._signature: one token for fifty minutes.
func (a *APNs) signature(now time.Time) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.token != "" && now.Sub(a.signedAt) < apnsTokenLifetime {
		return a.token, nil
	}
	block, _ := pem.Decode([]byte(strings.ReplaceAll(a.PrivateKey, `\n`, "\n")))
	if block == nil {
		return "", rejected("The APNs key is not a PEM private key.")
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return "", rejected("The APNs key cannot be read: " + err.Error())
	}
	key, ok := parsed.(*ecdsa.PrivateKey)
	if !ok {
		return "", rejected("The APNs key is not an EC key.")
	}
	token, err := es256(key, map[string]any{"typ": "JWT", "alg": "ES256", "kid": a.KeyID},
		[]jwtField{{"iss", a.TeamID}, {"iat", now.Unix()}})
	if err != nil {
		return "", err
	}
	a.token, a.signedAt = token, now
	return token, nil
}

// Send is apns.send.
func (a *APNs) Send(ctx context.Context, deviceToken string, payload orderedObject, priority, collapseID string,
	expiresIn time.Duration, now time.Time) error {
	str := func(name, fallback string) string {
		if s, _ := payload.field(name).(string); s != "" {
			return s
		}
		return fallback
	}
	body, err := encodeJSON(orderedObject{
		{"aps", orderedObject{
			{"alert", orderedObject{{"title", str("title", "")}, {"body", str("body", "")}}},
			{"sound", "default"},
			{"thread-id", str("category", "edify")},
		}},
		{"url", str("url", "/notifications")},
		{"id", str("id", "")},
	})
	if err != nil {
		return err
	}
	signature, err := a.signature(now)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.host+"/3/device/"+deviceToken, strings.NewReader(string(body)))
	if err != nil {
		return err
	}
	apnsPriority := "5"
	if priority == "high" || priority == "urgent" {
		apnsPriority = "10"
	}
	req.Header.Set("authorization", "bearer "+signature)
	req.Header.Set("apns-topic", a.Topic)
	req.Header.Set("apns-push-type", "alert")
	req.Header.Set("apns-priority", apnsPriority)
	req.Header.Set("apns-expiration", strconv.FormatInt(now.Unix()+int64(expiresIn/time.Second), 10))
	if collapseID != "" {
		if len(collapseID) > 64 {
			collapseID = collapseID[:64]
		}
		req.Header.Set("apns-collapse-id", collapseID)
	}
	resp, err := a.client.Do(req)
	if err != nil {
		return unavailable(fmt.Sprintf("%T: %v", err, err))
	}
	defer resp.Body.Close()
	if resp.StatusCode == 200 {
		return nil
	}
	var answer map[string]any
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	_ = json.Unmarshal(raw, &answer)
	reason := ""
	if r, ok := answer["reason"]; ok && r != nil {
		reason = fmt.Sprint(r)
	}
	detail := strings.TrimSpace(fmt.Sprintf("%d %s", resp.StatusCode, reason))
	switch {
	case resp.StatusCode == 410 || apnsGoneReasons[reason]:
		return gone(detail)
	case resp.StatusCode == 403 && reason == "ExpiredProviderToken":
		a.forget()
		return unavailable(detail)
	case resp.StatusCode == 429 || resp.StatusCode >= 500:
		return unavailable(detail)
	}
	return rejected(detail)
}
