package iapages

import "testing"

func TestPythonJSONWritesFloatsAsPythonDoes(t *testing.T) {
	got, err := PythonJSON(map[string]any{"b": 6.0, "a": []any{0.75, 1, nil, true, "x"}, "c": 1e-05, "d": 123456789.5, "e": 2e16})
	if err != nil {
		t.Fatal(err)
	}
	want := `{"a": [0.75, 1, null, true, "x"], "b": 6.0, "c": 1e-05, "d": 123456789.5, "e": 2e+16}`
	if string(got) != want {
		t.Fatalf("got  %s\nwant %s", got, want)
	}
}
