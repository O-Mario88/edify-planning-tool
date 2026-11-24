package audit

import (
	"math"
	"testing"
)

// The expected strings and hashes were produced by the existing
// application's own apps/core/audit_hash.py, so these tests fail the moment
// the two systems would disagree about a row.
func TestTheChainHashesExactlyAsTheExistingApplicationDoes(t *testing.T) {
	cases := []struct {
		name      string
		entry     Entry
		canonical string
		hash      string
	}{
		{
			name: "a failed sign-in",
			entry: Entry{Action: "auth.login_failed", SubjectKind: Text("User"), SubjectID: Text("cu1"),
				ActorID: Text("cu1"), ActorRole: Text("CCEO"), Success: false, Reason: Text("invalid_password"),
				Payload: map[string]any{"email": "a@b.org"}},
			canonical: `["auth.login_failed","User","cu1","cu1","CCEO",false,"invalid_password",null,null,null,{"email":"a@b.org"}]`,
			hash:      "323207bbd5f368c628dd89824a6e910fb26927a07f3496dfba721775004d8dec",
		},
		{
			name: "a lockout, with no payload",
			entry: Entry{Action: "auth.lockout_started", SubjectKind: Text("User"), SubjectID: Text("u2"),
				ActorID: Text("system"), ActorRole: Text("System"), Success: true,
				Reason: Text("10 consecutive failed logins -- locked 15 minute(s).")},
			canonical: `["auth.lockout_started","User","u2","system","System",true,"10 consecutive failed logins -- locked 15 minute(s).",null,null,null,null]`,
			hash:      "34fb6bb147968e514ae55e4c52ef4337d699fcc378fb3de493c83f5fb14600d4",
		},
		{
			name: "sorted keys, escapes and non-ASCII text",
			entry: Entry{Action: "x", Success: true, IPAddress: Text("127.0.0.1"), UserAgent: Text("Edify/1.0"),
				CorrelationID: Text("abc"), Payload: map[string]any{
					"z": 1, "a": []any{true, nil, "é\n\"q\"\t\x01"}, "m": map[string]any{"b": 2, "a": "Kampala – Ug"},
				}},
			canonical: `["x",null,null,null,null,true,null,"127.0.0.1","Edify/1.0","abc",{"a":[true,null,"é\n\"q\"\t\u0001"],"m":{"a":"Kampala – Ug","b":2},"z":1}]`,
			hash:      "58188bd78d71c4265bc64f13fee9b4af1419e7f2086d753551f41c2b192eb9a6",
		},
	}
	previous := ""
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := Canonical(tc.entry)
			if err != nil {
				t.Fatal(err)
			}
			if got != tc.canonical {
				t.Fatalf("canonical\n got %s\nwant %s", got, tc.canonical)
			}
			if hash := ChainHash(previous, got); hash != tc.hash {
				t.Fatalf("hash %s, want %s", hash, tc.hash)
			}
			previous = tc.hash
		})
	}
}

// The expected strings are Python's own repr() of each float, which
// stable_stringify prints for a fractional number.
func TestAFractionalNumberIsHashedAsPythonsRepr(t *testing.T) {
	cases := map[float64]string{
		5.6: "5.6", 0.1: "0.1", 3.25: "3.25", 1e-05: "1e-05", 0.0001: "0.0001", 1.5e-07: "1.5e-07",
		123456.789: "123456.789", -2.5: "-2.5", 1234567.5: "1234567.5", 5.125: "5.125",
		0.30000000000000004: "0.30000000000000004", 9999999999999.5: "9999999999999.5",
		0.00030000000000000003: "0.00030000000000000003", 2.675: "2.675", -0.0001: "-0.0001",
	}
	for v, want := range cases {
		if got, err := StableStringify(v); err != nil || got != want {
			t.Fatalf("%v: got %q, %v; want %q", v, got, err, want)
		}
	}
	if got, err := StableStringify(map[string]any{"n": 3.0}); err != nil || got != `{"n":3}` {
		t.Fatalf("an integral float: %q %v", got, err)
	}
	entry := Entry{Action: "ssa_create", SubjectKind: Text("SsaRecord"), SubjectID: Text("r1"), ActorID: Text("u1"),
		ActorRole: Text("CCEO"), Success: true, Payload: map[string]any{
			"averageScore": 5.6, "scores": map[string]any{"leadership": 7.0, "teaching_environment": 3.25, "tiny": 1e-05}}}
	got, err := Canonical(entry)
	want := `["ssa_create","SsaRecord","r1","u1","CCEO",true,null,null,null,null,{"averageScore":5.6,"scores":{"leadership":7,"teaching_environment":3.25,"tiny":1e-05}}]`
	if err != nil || got != want {
		t.Fatalf("canonical\n got %s, %v\nwant %s", got, err, want)
	}
	if hash := ChainHash("", got); hash != "56370a51284f82c67bbb977bf0907cbaec794305b907646dab8dbe2af3930926" {
		t.Fatalf("hash %s", hash)
	}
	for _, v := range []float64{math.NaN(), math.Inf(1)} {
		if _, err := StableStringify(v); err == nil {
			t.Fatalf("%v was accepted", v)
		}
	}
}
