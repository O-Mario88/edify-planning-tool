package pushdelivery

import (
	"bytes"
	"crypto"
	"crypto/ecdsa"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/json"
	"sort"
)

// jwtField is one claim, in the order the existing code writes it.
type jwtField struct {
	name  string
	value any
}

// encodeJSON is json.dumps(separators=(",", ":"), ensure_ascii=False): no
// spaces, characters written as themselves.
func encodeJSON(value any) ([]byte, error) {
	var out bytes.Buffer
	enc := json.NewEncoder(&out)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(value); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(out.Bytes(), []byte("\n")), nil
}

// orderedObject writes fields in the given order, as a Python dict keeps its
// insertion order.
type orderedObject []jwtField

func (o orderedObject) MarshalJSON() ([]byte, error) {
	var out bytes.Buffer
	out.WriteByte('{')
	for i, f := range o {
		if i > 0 {
			out.WriteByte(',')
		}
		key, err := encodeJSON(f.name)
		if err != nil {
			return nil, err
		}
		value, err := encodeJSON(f.value)
		if err != nil {
			return nil, err
		}
		out.Write(key)
		out.WriteByte(':')
		out.Write(value)
	}
	out.WriteByte('}')
	return out.Bytes(), nil
}

// signingInput is PyJWT's: the header with its keys sorted, the claims in
// their order, each base64url.
func signingInput(header map[string]any, claims []jwtField) (string, error) {
	keys := make([]string, 0, len(header))
	for k := range header {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	sorted := orderedObject{}
	for _, k := range keys {
		sorted = append(sorted, jwtField{k, header[k]})
	}
	h, err := encodeJSON(sorted)
	if err != nil {
		return "", err
	}
	c, err := encodeJSON(orderedObject(claims))
	if err != nil {
		return "", err
	}
	return b64url(h) + "." + b64url(c), nil
}

// es256 is jwt.encode(..., algorithm="ES256"): the signature as r‖s.
func es256(key *ecdsa.PrivateKey, header map[string]any, claims []jwtField) (string, error) {
	input, err := signingInput(header, claims)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256([]byte(input))
	r, s, err := ecdsa.Sign(rand.Reader, key, digest[:])
	if err != nil {
		return "", err
	}
	signature := make([]byte, 64)
	r.FillBytes(signature[:32])
	s.FillBytes(signature[32:])
	return input + "." + b64url(signature), nil
}

// rs256 is jwt.encode(..., algorithm="RS256").
func rs256(key *rsa.PrivateKey, header map[string]any, claims []jwtField) (string, error) {
	input, err := signingInput(header, claims)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256([]byte(input))
	signature, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, digest[:])
	if err != nil {
		return "", err
	}
	return input + "." + b64url(signature), nil
}
