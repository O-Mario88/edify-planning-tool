package support

import "testing"

func TestTicketNoticeIsTheServicesWords(t *testing.T) {
	if got := ticketNoticeBody("CCEO", "dead_button", "/planning"); got != "CCEO reported Dead Button on /planning." {
		t.Errorf("body = %q", got)
	}
	if got := ticketNoticeBody("", "something_new", ""); got != "A user reported something_new on an unknown page." {
		t.Errorf("fallbacks = %q", got)
	}
	if got := ticketNoticeBody("Program Lead", "missing_data", "/schools"); got != "Program Lead reported Missing School / Activity / Budget on /schools." {
		t.Errorf("label = %q", got)
	}
}

func TestRequestContextFillsWhatTheCallerLeftOut(t *testing.T) {
	got := withRequestContext(map[string]string{"route": "/planning"}, "Mozilla/5.0", "abc123")
	if got["route"] != "/planning" || got["browser"] != "Mozilla/5.0" || got["request_id"] != "abc123" {
		t.Errorf("context = %v", got)
	}
	kept := withRequestContext(map[string]string{"browser": "given"}, "Mozilla/5.0", "")
	if kept["browser"] != "given" || kept["request_id"] != "" {
		t.Errorf("kept = %v", kept)
	}
}
