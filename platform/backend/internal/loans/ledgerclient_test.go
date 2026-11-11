package loans

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// What the gateway sends the existing ledger: the signed-in person's own
// token (so the existing application applies their permissions and lender
// scope), a stable idempotency key, and allocations that add up.

type ledgerCall struct {
	path, bearer string
	body         map[string]any
}

func fakeLedger(t *testing.T, status int, answer string) (*LedgerClient, *[]ledgerCall) {
	t.Helper()
	var calls []ledgerCall
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(request.Body).Decode(&body)
		calls = append(calls, ledgerCall{path: request.URL.EscapedPath(), bearer: request.Header.Get("Authorization"), body: body})
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(status)
		_, _ = writer.Write([]byte(answer))
	}))
	t.Cleanup(server.Close)
	return NewLedgerClient(server.URL), &calls
}

func TestARepaymentIsPostedAsThePersonVerifyingIt(t *testing.T) {
	client, calls := fakeLedger(t, http.StatusCreated, `{"id":"tx1"}`)
	ctx := auth.WithBearer(context.Background(), "finance-officer-token")
	day := time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)
	id, err := client.PostRepayment(ctx, RepaymentPosting{LoanID: "loan/1", IdempotencyKey: "evidence:ev1",
		Amount: ledger.Shillings(5_000_000), ExternalReference: "STB-1", ReceivedOn: day, ValueDate: day,
		Allocations: []ledger.Allocation{{InstallmentID: "i1", Component: ledger.Interest, Amount: ledger.Shillings(900_000)},
			{InstallmentID: "i1", Component: ledger.Principal, Amount: ledger.Shillings(4_100_000)}}})
	if err != nil || id != "tx1" {
		t.Fatalf("id %q err %v", id, err)
	}
	call := (*calls)[0]
	if call.path != "/api/business-transformation/repayment-transactions" || call.bearer != "Bearer finance-officer-token" {
		t.Fatalf("posted to %s as %q", call.path, call.bearer)
	}
	if call.body["idempotencyKey"] != "evidence:ev1" || call.body["amount"] != "5000000.00" || call.body["valueDate"] != "2026-11-11" {
		t.Fatalf("body %v", call.body)
	}
	var total float64
	for _, raw := range call.body["allocations"].([]any) {
		amount, _ := raw.(map[string]any)["amount"].(string)
		m, err := ledger.ParseMoney(amount)
		if err != nil {
			t.Fatal(err)
		}
		total += float64(m)
	}
	if ledger.Money(total) != ledger.Shillings(5_000_000) {
		t.Fatalf("allocations add up to %v", total)
	}
}

func TestLedgerPathsEscapeTheirIDs(t *testing.T) {
	client, calls := fakeLedger(t, http.StatusOK, `{}`)
	if err := client.PostSchedule(context.Background(), "a/b?c", 1, nil); err != nil {
		t.Fatal(err)
	}
	if got := (*calls)[0].path; got != "/api/business-transformation/loans/a%2Fb%3Fc/repayment-schedule" {
		t.Fatalf("path %q", got)
	}
}

func TestALedgerRefusalKeepsItsReasonAndAnOutageIsNotARefusal(t *testing.T) {
	client, _ := fakeLedger(t, http.StatusConflict, `{"message":"The facility does not have enough original capital available."}`)
	_, err := client.PostRepayment(context.Background(), RepaymentPosting{LoanID: "l"})
	var refusal *LedgerRefusal
	if !errors.As(err, &refusal) || refusal.Message != "The facility does not have enough original capital available." {
		t.Fatalf("got %v", err)
	}
	down, _ := fakeLedger(t, http.StatusBadGateway, `upstream down`)
	if _, err := down.PostRepayment(context.Background(), RepaymentPosting{LoanID: "l"}); !errors.Is(err, ErrLedgerUnavailable) {
		t.Fatalf("a 502 was not reported as the ledger being unreachable: %v", err)
	}
	if _, err := NewLedgerClient("").PostRepayment(context.Background(), RepaymentPosting{}); !errors.Is(err, ErrLedgerUnavailable) {
		t.Fatalf("no configured ledger: %v", err)
	}
}
