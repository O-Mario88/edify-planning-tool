package pushdelivery

import (
	"context"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	fcmTokenURL          = "https://oauth2.googleapis.com/token"
	fcmSendURL           = "https://fcm.googleapis.com/v1/projects/%s/messages:send"
	fcmScope             = "https://www.googleapis.com/auth/firebase.messaging"
	androidChannel       = "edify"
	renewBefore          = 5 * time.Minute
	assertionLifetime    = time.Hour
	fcmTokenMin, tokenMx = 32, 4096
)

var (
	fcmToken       = regexp.MustCompile(`^[A-Za-z0-9_\-]+:[A-Za-z0-9_\-.]+$`)
	rawAPNsToken   = regexp.MustCompile(`^[0-9a-fA-F]{64}$`)
	retryableCodes = []string{"UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED"}
	goneCodes      = []string{"UNREGISTERED", "SENDER_ID_MISMATCH"}
)

// serviceAccount is fcm.ServiceAccount.
type serviceAccount struct {
	ProjectID, ClientEmail, PrivateKey, KeyID string
}

// parseServiceAccount is fcm._parse: JSON, or base64 of it, naming the
// project, the client and the key.
func parseServiceAccount(raw string) (*serviceAccount, bool) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return nil, false
	}
	if !strings.HasPrefix(text, "{") {
		decoded, err := base64.StdEncoding.Strict().DecodeString(text)
		if err != nil {
			return nil, false
		}
		text = string(decoded)
	}
	var data map[string]any
	if err := json.Unmarshal([]byte(text), &data); err != nil {
		return nil, false
	}
	str := func(k string) string { s, _ := data[k].(string); return s }
	if strings.TrimSpace(str("project_id")) == "" || strings.TrimSpace(str("client_email")) == "" ||
		strings.TrimSpace(str("private_key")) == "" {
		return nil, false
	}
	keyID := ""
	if v, ok := data["private_key_id"]; ok && v != nil {
		keyID = fmt.Sprint(v)
	}
	return &serviceAccount{ProjectID: strings.TrimSpace(str("project_id")), ClientEmail: strings.TrimSpace(str("client_email")),
		PrivateKey: str("private_key"), KeyID: keyID}, true
}

// validFCMToken is fcm.valid_token.
func validFCMToken(token string) bool {
	if len(token) < fcmTokenMin || len(token) > tokenMx {
		return false
	}
	return fcmToken.MatchString(token) && !rawAPNsToken.MatchString(token)
}

// fcmMessage is message_for: shown by the phone, with the notice's id and
// address as data for the tap.
func fcmMessage(token string, payload orderedObject, ttl time.Duration, urgent bool, collapse string, now time.Time) map[string]any {
	data := map[string]any{}
	for _, f := range payload {
		if f.value != nil {
			data[f.name] = fmt.Sprint(f.value)
		}
	}
	if collapse == "" {
		collapse = "edify"
	}
	if len(collapse) > 64 {
		collapse = collapse[:64]
	}
	or := func(v any, fallback string) string {
		if s, _ := v.(string); s != "" {
			return s
		}
		return fallback
	}
	priority, apnsPriority := "NORMAL", "5"
	if urgent {
		priority, apnsPriority = "HIGH", "10"
	}
	seconds := int64(ttl / time.Second)
	return map[string]any{
		"token":        token,
		"notification": map[string]any{"title": or(payload.field("title"), "Edify"), "body": or(payload.field("body"), "")},
		"data":         data,
		"android": map[string]any{
			"priority": priority, "ttl": strconv.FormatInt(seconds, 10) + "s", "collapse_key": collapse,
			"notification": map[string]any{"tag": or(payload.field("tag"), "edify"), "channel_id": androidChannel,
				"visibility": "PRIVATE"},
		},
		"apns": map[string]any{
			"headers": map[string]any{"apns-priority": apnsPriority, "apns-collapse-id": collapse,
				"apns-expiration": strconv.FormatInt(now.Unix()+seconds, 10)},
			"payload": map[string]any{"aps": map[string]any{"sound": "default", "thread-id": or(payload.field("category"), "edify")}},
		},
	}
}

// FCM sends through Firebase with the deployment's service account.
type FCM struct {
	account *serviceAccount
	client  *http.Client
	mu      sync.Mutex
	held    map[[2]string]heldToken
	urls    struct{ token, send string }
}

type heldToken struct {
	token   string
	expires time.Time
}

// NewFCM is the Firebase sender for a raw service account (JSON or base64);
// nil when there is none.
func NewFCM(raw string, client *http.Client) *FCM {
	account, ok := parseServiceAccount(raw)
	if !ok {
		return nil
	}
	f := &FCM{account: account, client: client, held: map[[2]string]heldToken{}}
	f.urls.token, f.urls.send = fcmTokenURL, fmt.Sprintf(fcmSendURL, account.ProjectID)
	return f
}

func (f *FCM) forget() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.held = map[[2]string]heldToken{}
}

func (f *FCM) assertion(now time.Time) (string, error) {
	block, _ := pem.Decode([]byte(f.account.PrivateKey))
	if block == nil {
		return "", rejected("The Firebase key is not a PEM private key.")
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		if pk1, err1 := x509.ParsePKCS1PrivateKey(block.Bytes); err1 == nil {
			parsed = pk1
		} else {
			return "", rejected("The Firebase key cannot be read: " + err.Error())
		}
	}
	key, ok := parsed.(*rsa.PrivateKey)
	if !ok {
		return "", rejected("The Firebase key is not an RSA key.")
	}
	header := map[string]any{"typ": "JWT", "alg": "RS256"}
	if f.account.KeyID != "" {
		header["kid"] = f.account.KeyID
	}
	return rs256(key, header, []jwtField{{"iss", f.account.ClientEmail}, {"scope", fcmScope}, {"aud", fcmTokenURL},
		{"iat", now.Unix()}, {"exp", now.Add(assertionLifetime).Unix()}})
}

// accessToken is _access_token: the token held, else one signed for.
func (f *FCM) accessToken(ctx context.Context, now time.Time) (string, error) {
	key := [2]string{f.account.ClientEmail, f.account.KeyID}
	f.mu.Lock()
	held, ok := f.held[key]
	f.mu.Unlock()
	if ok && held.expires.Add(-renewBefore).After(now) {
		return held.token, nil
	}
	assertion, err := f.assertion(now)
	if err != nil {
		return "", err
	}
	form := url.Values{"grant_type": {"urn:ietf:params:oauth:grant-type:jwt-bearer"}, "assertion": {assertion}}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, f.urls.token, strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := f.client.Do(req)
	if err != nil {
		return "", unavailable(fmt.Sprintf("%T: %v", err, err))
	}
	defer resp.Body.Close()
	if resp.StatusCode == 429 || resp.StatusCode >= 500 {
		return "", unavailable(fmt.Sprintf("Google sign-in answered %d", resp.StatusCode))
	}
	var body map[string]any
	_ = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&body)
	token, _ := body["access_token"].(string)
	if resp.StatusCode != 200 || token == "" {
		return "", rejected(fmt.Sprintf("Google refused the Firebase key (%d %v)", resp.StatusCode, valueOr(body["error"], "")))
	}
	expiresIn := 3600.0
	if v, ok := body["expires_in"].(float64); ok && v != 0 {
		expiresIn = v
	}
	f.mu.Lock()
	f.held[key] = heldToken{token, now.Add(time.Duration(expiresIn * float64(time.Second)))}
	f.mu.Unlock()
	return token, nil
}

func valueOr(v any, fallback string) any {
	if v == nil {
		return fallback
	}
	return v
}

// failureOf is fcm._failure: the outcome a refused send stands for.
func (f *FCM) failureOf(status int, body map[string]any) error {
	errObj, _ := body["error"].(map[string]any)
	message, _ := errObj["message"].(string)
	word, _ := errObj["status"].(string)
	codes := map[string]bool{}
	if details, ok := errObj["details"].([]any); ok {
		for _, d := range details {
			if item, ok := d.(map[string]any); ok {
				if code, ok := item["errorCode"].(string); ok && code != "" {
					codes[code] = true
				}
			}
		}
	}
	sorted := make([]string, 0, len(codes))
	for c := range codes {
		sorted = append(sorted, c)
	}
	sort.Strings(sorted)
	label := strings.Join(sorted, ", ")
	if label == "" {
		label = word
	}
	detail := strings.TrimSpace(fmt.Sprintf("%d %s %s", status, label, message))
	if len(detail) > 240 {
		detail = detail[:240]
	}
	anyOf := func(list []string) bool {
		for _, c := range list {
			if codes[c] {
				return true
			}
		}
		return false
	}
	switch {
	case codes["THIRD_PARTY_AUTH_ERROR"]:
		return rejected(detail)
	case status == 404 || anyOf(goneCodes):
		return gone(detail)
	case status == 400 && strings.Contains(strings.ToLower(message), "registration token"):
		return gone(detail)
	case status == 401:
		f.forget()
		return unavailable(detail)
	case status == 429 || status >= 500 || anyOf(retryableCodes):
		return unavailable(detail)
	}
	return rejected(detail)
}

// Send is fcm.send; it says the message name Firebase gave.
func (f *FCM) Send(ctx context.Context, token string, payload orderedObject, ttl time.Duration, urgent bool,
	collapse string, now time.Time) (string, error) {
	if !validFCMToken(token) {
		return "", gone("That is not an FCM registration token.")
	}
	access, err := f.accessToken(ctx, now)
	if err != nil {
		return "", err
	}
	body, err := json.Marshal(map[string]any{"message": fcmMessage(token, payload, ttl, urgent, collapse, now)})
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, f.urls.send, strings.NewReader(string(body)))
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+access)
	req.Header.Set("Content-Type", "application/json")
	resp, err := f.client.Do(req)
	if err != nil {
		return "", unavailable(fmt.Sprintf("%T: %v", err, err))
	}
	defer resp.Body.Close()
	var answer map[string]any
	_ = json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&answer)
	if resp.StatusCode == 200 {
		name, _ := answer["name"].(string)
		return name, nil
	}
	return "", f.failureOf(resp.StatusCode, answer)
}

// NoRedirects is allow_redirects=False: a push service answers the address
// it was given, and the redirect's own answer is the outcome.
func NoRedirects(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
