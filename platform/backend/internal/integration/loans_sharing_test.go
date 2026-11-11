//go:build integration

package integration

import (
	"context"
	"net/http"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
)

// Sharing the application against a real database: the public link needs
// no account, a lender's fixed link sends only to that lender, a sharer's
// link is counted on the application, invitations fail safely once
// replaced, and tracking never says whether a reference exists.

func linkActor() loans.LinkActor {
	return loans.LinkActor{ID: "integration-sharer", Name: "Integration Sharer", Role: "BusinessTransformationOfficer"}
}

func TestSharedLinksOpenThePublicFormAndAttributeApplications(t *testing.T) {
	loanFixtures(t)
	ctx := context.Background()
	store := loans.NewStore(gateway)
	browser := schoolClient(t)

	// 1. The universal link opens without an account; the first links move.
	response, page := fetch(t, browser, http.MethodGet, "/loans/apply", nil)
	if response.StatusCode != http.StatusOK || !strings.Contains(page, `action="/loans/apply"`) {
		t.Fatalf("the universal link answered %d", response.StatusCode)
	}
	if !strings.Contains(page, `og:description" content="Edify school loans. No account or password needed."`) {
		t.Fatal("the link preview text is missing or not the generic one")
	}
	if response, _ := fetch(t, browser, http.MethodGet, "/apply/school-loan?invite=abc", nil); response.StatusCode != http.StatusMovedPermanently ||
		response.Header.Get("Location") != "/loans/apply/i/abc" {
		t.Fatalf("the first link answered %d to %q", response.StatusCode, response.Header.Get("Location"))
	}

	// 2. A lender's fixed link shows that lender only and refuses another.
	partner, err := store.PartnerLink(ctx, lenderA, linkActor(), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if !partner.LockPartner {
		t.Fatal("a lender's link should fix the lender unless its policy says otherwise")
	}
	_, page = fetch(t, browser, http.MethodGet, "/loans/apply/p/"+partner.ID, nil)
	if !strings.Contains(page, "This link is from Integration Lender A") || strings.Contains(page, `<select id="partner"`) {
		t.Fatal("the fixed link does not fix the lender")
	}
	form := applicationForm(lenderB, "Fixed Lender School", "0772 000 401", "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
	form.Set("link", partner.ID)
	if response := submit(t, form); response.StatusCode != http.StatusUnprocessableEntity {
		t.Fatalf("an application to another lender through a fixed link answered %d", response.StatusCode)
	}
	form.Set("partner", lenderA)
	if response := submit(t, form); response.StatusCode != http.StatusSeeOther ||
		!strings.HasPrefix(response.Header.Get("Location"), "/loans/apply/receipt/") {
		t.Fatalf("the fixed link's own lender answered %d to %q", response.StatusCode, response.Header.Get("Location"))
	}
	var linked, lender string
	if err := admin.QueryRow(ctx, `SELECT COALESCE(share_link_id, ''), partner_id FROM school_loans.application WHERE director_phone = '+256772000401'`).
		Scan(&linked, &lender); err != nil || linked != partner.ID || lender != lenderA {
		t.Fatalf("stored link %q lender %q (%v)", linked, lender, err)
	}

	// 3. A sharer's link is counted, never trusted for anything else.
	referral, err := store.ReferralLink(ctx, "", linkActor(), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	again, err := store.ReferralLink(ctx, "", linkActor(), time.Now())
	if err != nil || again.ID != referral.ID {
		t.Fatal("a sharer's link changed between two requests")
	}
	form = applicationForm(lenderB, "Referred School", "0772 000 402", "ffffffffffffffffffffffffffffffff")
	form.Set("link", referral.ID)
	if response := submit(t, form); response.StatusCode != http.StatusSeeOther {
		t.Fatalf("a referred application answered %d", response.StatusCode)
	}
	if err := admin.QueryRow(ctx, `SELECT COALESCE(share_link_id, '') FROM school_loans.application WHERE director_phone = '+256772000402'`).
		Scan(&linked); err != nil || linked != referral.ID {
		t.Fatalf("the referral was not counted: %q (%v)", linked, err)
	}
	if err := store.ReplaceShareLink(ctx, referral, linkActor(), time.Now()); err != nil {
		t.Fatal(err)
	}
	if _, page := fetch(t, browser, http.MethodGet, "/loans/apply/r/"+referral.ID, nil); !strings.Contains(page, "replaced or is not valid") {
		t.Fatal("a replaced link did not say so")
	}
	if response, _ := fetch(t, browser, http.MethodGet, "/loans/apply/r/"+referral.ID+"/qr.png", nil); response.StatusCode != http.StatusNotFound {
		t.Fatalf("a replaced link still drew a QR code: %d", response.StatusCode)
	}

	// 4. An invitation names the school only, and fails safely once replaced.
	var schoolID, schoolName string
	if err := admin.QueryRow(ctx, `SELECT id, name FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&schoolID, &schoolName); err != nil {
		t.Fatal(err)
	}
	school, err := store.School(ctx, schoolID)
	if err != nil {
		t.Fatal(err)
	}
	token, invitation, err := store.InviteSchool(ctx, school, linkActor(), "bto", "", time.Now())
	if err != nil {
		t.Fatal(err)
	}
	_, page = fetch(t, browser, http.MethodGet, "/loans/apply/i/"+token, nil)
	if !strings.Contains(page, "This link was sent to") || strings.Contains(page, `og:title" content="`+schoolName) {
		t.Fatal("the invitation does not name its school, or leaks it into the link preview")
	}
	newer, _, err := store.InviteSchool(ctx, school, linkActor(), "bto", "", time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if _, page := fetch(t, browser, http.MethodGet, "/loans/apply/i/"+token, nil); !strings.Contains(page, "expired or is not valid") {
		t.Fatal("an invitation replaced by a newer one still works")
	}
	if _, err := store.RevokeInvitation(ctx, invitation.ID, "test", linkActor(), time.Now()); err == nil {
		t.Fatal("revoking an already-replaced invitation succeeded")
	}
	if _, page := fetch(t, browser, http.MethodGet, "/loans/apply/i/"+newer, nil); !strings.Contains(page, "This link was sent to") {
		t.Fatal("the newer invitation does not work")
	}
}

func TestTrackingNeverSaysWhetherAReferenceExists(t *testing.T) {
	loanFixtures(t)
	submit(t, applicationForm(lenderA, "Tracked School", "0772 000 501", "abababababababababababababababab"))
	_, reference := applicationByPhone(t, "+256772000501")
	browser := schoolClient(t)
	countTexts := func() int {
		entries, _ := os.ReadDir(smsbox)
		return len(entries)
	}

	before := countTexts()
	_, wrong := fetch(t, browser, http.MethodPost, "/loans/track/code", url.Values{"reference": {"EDL-0000-0000"}, "phone": {"0772000501"}})
	_, wrongPhone := fetch(t, browser, http.MethodPost, "/loans/track/code", url.Values{"reference": {reference}, "phone": {"0772999999"}})
	if countTexts() != before {
		t.Fatal("a code was sent for a reference and phone that do not match")
	}
	_, right := fetch(t, browser, http.MethodPost, "/loans/track/code", url.Values{"reference": {reference}, "phone": {"0772000501"}})
	if countTexts() != before+1 {
		t.Fatal("no code was texted for a matching reference and phone")
	}
	answer := func(page string) string {
		start := strings.Index(page, `<div class="notice notice--info"`)
		if start < 0 {
			return ""
		}
		end := strings.Index(page[start:], "</div>")
		return page[start : start+end]
	}
	if answer(right) == "" || answer(wrong) != answer(right) || answer(wrongPhone) != answer(right) {
		t.Fatal("the answer differs when the reference or phone is wrong")
	}

	// A code for one reference opens nothing for another.
	code := latestCodeTo(t, "+256772000501")
	if response, _ := fetch(t, browser, http.MethodPost, "/loans/track/verify", url.Values{"reference": {"EDL-0000-0000"}, "code": {code}}); response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("a code opened another reference: %d", response.StatusCode)
	}
	response, _ := fetch(t, browser, http.MethodPost, "/loans/track/verify", url.Values{"reference": {reference}, "code": {code}})
	if response.StatusCode != http.StatusSeeOther || !strings.Contains(response.Header.Get("Set-Cookie"), "Path=/loans/track") {
		t.Fatalf("the right code answered %d", response.StatusCode)
	}
	response, page := fetch(t, browser, http.MethodGet, "/loans/track/view", nil)
	if response.StatusCode != http.StatusOK || !strings.Contains(page, reference) || !strings.Contains(page, "Application submitted") {
		t.Fatalf("the tracking page answered %d without the application", response.StatusCode)
	}
	if strings.Contains(page, "Outstanding") || strings.Contains(page, "Integration Director") {
		t.Fatal("tracking shows statement figures or people's names")
	}
	// The tracking session opens no statement.
	if response, _ := fetch(t, browser, http.MethodGet, "/loan/statement/view", nil); response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("a tracking session opened the statement: %d", response.StatusCode)
	}
}
