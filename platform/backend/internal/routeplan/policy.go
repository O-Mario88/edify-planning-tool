package routeplan

import (
	"fmt"
	"math"
	"slices"
	"strings"
	"time"
)

// The location capture policy (owner brief and decisions, 2026-11-14). A
// first location for a school with none, captured by GPS at the policy's
// accuracy by a CCEO or Program Lead, is accepted at once. Everything else
// (every correction, every entrance point, a typed point, a poorer fix, a
// capture made against an older version) waits for a reviewer. Nothing is
// refused for being far from the old point: a school may have moved.

// ReviewerRoles are the roles that decide location reports and captures
// (owner, 2026-11-14).
var ReviewerRoles = []string{"Program Lead", "CountryDirector", "Admin"}

// CaptureRoles are legacy offline-pack roles whose first captures auto-accept.
var CaptureRoles = []string{"CCEO", "Program Lead"}

// GPSCaptureRoles may use the interactive mobile/web GPS Coordinate Capture &
// Update flow for schools within their authorized scope (schoolByRef strictly
// enforces per-user & partner reach).
var GPSCaptureRoles = []string{
	"CCEO",
	"Program Lead",
	"CountryDirector",
	"Admin",
	"ProjectCoordinator",
	"PartnerFieldOfficer",
	"PartnerAdmin",
}

// MayCaptureGPS reports whether role may use the mobile/web GPS capture flow.
func MayCaptureGPS(role string) bool { return slices.Contains(GPSCaptureRoles, role) }

// DirectCaptureRoles are Edify staff roles whose normal, accurate, fresh GPS
// updates apply directly (while large/suspicious moves or poor accuracy still
// queue for supervisor verification).
var DirectCaptureRoles = []string{"CCEO", "Program Lead", "CountryDirector", "Admin", "ProjectCoordinator"}

// DecideGPSCapture evaluates a device GPS capture/update from POST /api/schools/{id}/gps-location:
// - Normal authorized captures & updates (accuracy <= 50m, displacement <= 1000m,
//   within district tolerance, no version conflict) apply directly & immediately.
// - Large moves (> 1000m), far-from-district coordinates (> 60km), poor accuracy (> 50m),
//   or partner updates without direct-save rights are stored as pending verification
//   so coordinates are never silently overwritten on suspicious readings.
func DecideGPSCapture(in CaptureInput, st SchoolState, role string, now time.Time, policy Policy) Decision {
	var flags []string
	add := func(f string) {
		if !slices.Contains(flags, f) {
			flags = append(flags, f)
		}
	}
	d := Decision{}
	if in.BaseVersion >= 0 && in.BaseVersion != st.Version {
		add("version_conflict")
	}
	if !slices.Contains(DirectCaptureRoles, role) {
		add("partner_review_required")
	}
	if in.AccuracyM > policy.ConfirmM {
		add("accuracy_poor")
	} else if in.AccuracyM > policy.GoodM {
		add("accuracy_fair")
	}
	if in.SpreadM > policy.ConfirmM {
		add("unstable")
	}
	if now.Sub(in.CapturedAt) > policy.MaxAge {
		add("stale_capture")
	}
	if in.CapturedAt.Sub(now) > policy.ClockSkew {
		add("clock_skew")
	}
	if in.Point != nil {
		if st.Placed {
			m := float64(StraightMeters(st.At, *in.Point))
			d.DisplacementM = &m
			if m > policy.LargeMoveM {
				add("large_move")
			}
		}
		if st.DistrictCentre != nil && float64(StraightMeters(*st.DistrictCentre, *in.Point)) > policy.FarFromDistrictM {
			add("far_from_district")
		}
	}
	d.Flags = flags
	blocking := []string{"version_conflict", "partner_review_required", "accuracy_poor", "large_move", "far_from_district", "stale_capture", "clock_skew"}
	hasBlocking := false
	for _, f := range flags {
		if slices.Contains(blocking, f) {
			hasBlocking = true
			break
		}
	}
	if !hasBlocking && in.Source == "device" {
		d.Status = CaptureAccepted
	} else {
		d.Status = CapturePending
	}
	return d
}

// MayReview is whether the role decides location reports.
func MayReview(role string) bool { return slices.Contains(ReviewerRoles, role) }

// MayCapture is whether the role captures school locations by GPS.
func MayCapture(role string) bool { return slices.Contains(CaptureRoles, role) }

// Policy is the thresholds a capture is judged by.
type Policy struct {
	// At or better than GoodM a fix is Good; up to ConfirmM the person
	// confirms it; beyond, the device recommends recapture.
	GoodM, ConfirmM float64
	// A device fix older than FreshSeconds when the person confirmed it is
	// stale (the device checks; the server sees only the capture time).
	FreshSeconds int32
	// A correction moving the point further than LargeMoveM is flagged.
	LargeMoveM float64
	// A capture synced later than MaxAge after it was taken is flagged.
	MaxAge time.Duration
	// A capture time this far past the server's clock is flagged.
	ClockSkew time.Duration
	// A point this far from its district's other schools is flagged.
	FarFromDistrictM float64
	// A device fix coarser than this is refused outright.
	MaxAccuracyM float64
}

// DefaultPolicy is the brief's proposed thresholds.
var DefaultPolicy = Policy{
	GoodM: 20, ConfirmM: 50, FreshSeconds: 120, LargeMoveM: 1000,
	MaxAge: 30 * 24 * time.Hour, ClockSkew: 10 * time.Minute, FarFromDistrictM: 60_000, MaxAccuracyM: 1000,
}

// Capture statuses.
const (
	CaptureAccepted = "accepted"
	CapturePending  = "pending"
	CaptureApproved = "approved"
	CaptureRejected = "rejected"
	CaptureNoted    = "noted"
)

// CaptureInput is a capture as sent, before it is checked.
type CaptureInput struct {
	Target, Kind, Source string
	Point                *LatLng
	AccuracyM            float64
	CapturedAt           time.Time
	SampleCount          int32
	SpreadM              float64
	BaseVersion          int32
	Reason, AccessNote   string
}

// CheckCapture is a capture's own rules; the message is what the person
// reads. It returns the capture cleaned.
func CheckCapture(in CaptureInput, policy Policy) (CaptureInput, string) {
	out := in
	out.Reason = strings.TrimSpace(in.Reason)
	out.AccessNote = strings.TrimSpace(in.AccessNote)
	if out.Target == "" {
		out.Target = "school"
	}
	switch {
	case out.Target != "school" && out.Target != "entrance":
		return out, "The capture could not be sent. Please try again."
	case out.Kind != "new" && out.Kind != "correction" && out.Kind != "confirm":
		return out, "The capture could not be sent. Please try again."
	case len([]rune(out.Reason)) > noteMaxRunes:
		return out, fmt.Sprintf("Keep the reason under %d characters.", noteMaxRunes)
	case len([]rune(out.AccessNote)) > accessNoteMaxRunes:
		return out, fmt.Sprintf("Keep the directions under %d characters.", accessNoteMaxRunes)
	case out.SampleCount < 0 || math.IsNaN(out.SpreadM) || out.SpreadM < 0:
		return out, "The capture could not be sent. Please try again."
	}
	if out.Kind == "confirm" {
		// "The location is correct": the answer is what counts.
		out.Point, out.Source, out.AccuracyM = nil, "none", 0
		return out, ""
	}
	if out.Kind == "correction" && out.Reason == "" {
		return out, "Say why the location is being corrected."
	}
	switch out.Source {
	case "", "none":
		out.Source, out.Point, out.AccuracyM = "none", nil, 0
		if out.Kind == "new" {
			return out, "Give the school's location: capture it or type it."
		}
		return out, ""
	case "typed", "device":
	default:
		return out, "The capture could not be sent. Please try again."
	}
	if out.Point == nil {
		return out, "Give the school's location: capture it or type it."
	}
	if _, ok := checkPoint(out.Point.Lat, out.Point.Lng); !ok {
		return out, "That point is not in Uganda. Check the latitude and longitude."
	}
	if out.Source == "typed" {
		out.AccuracyM, out.SampleCount, out.SpreadM = 0, 0, 0
		return out, ""
	}
	if math.IsNaN(out.AccuracyM) || math.IsInf(out.AccuracyM, 0) || out.AccuracyM <= 0 {
		return out, "Your device did not say how accurate its location is. Please capture again."
	}
	if out.AccuracyM > policy.MaxAccuracyM {
		return out, fmt.Sprintf("That reading is only accurate to %.0f m. Move into the open and capture again.", out.AccuracyM)
	}
	if out.CapturedAt.IsZero() {
		return out, "The capture has no time. Please capture again."
	}
	return out, ""
}

// SchoolState is what the server holds for the capture's school and target.
type SchoolState struct {
	// Placed and At: the target's current usable point, if any.
	Placed bool
	At     LatLng
	// Version: the target's current location version.
	Version int32
	// Pending: other captures on the same school and target waiting for review.
	Pending int
	// DistrictCentre: the middle of the district's other schools, if known.
	DistrictCentre *LatLng
}

// Decision is what happens to a capture.
type Decision struct {
	Status        string
	Flags         []string
	DisplacementM *float64
}

// Decide applies the policy to a checked capture.
func Decide(in CaptureInput, st SchoolState, role string, now time.Time, policy Policy) Decision {
	if in.Kind == "confirm" {
		d := Decision{Status: CaptureNoted}
		if in.BaseVersion != st.Version {
			// The answer was about a point that has since changed.
			d.Flags = []string{"version_conflict"}
		}
		return d
	}
	var flags []string
	add := func(f string) {
		if !slices.Contains(flags, f) {
			flags = append(flags, f)
		}
	}
	d := Decision{}
	if in.Target == "entrance" {
		add("entrance")
	}
	if in.Kind == "correction" || st.Placed {
		// A correction, or a "new" capture for a school that has a point by now.
		add("correction")
	}
	if in.Kind == "new" && st.Placed {
		add("version_conflict")
	}
	if in.BaseVersion != st.Version {
		add("version_conflict")
	}
	if !MayCapture(role) {
		add("reporter_role")
	}
	if st.Pending > 0 {
		add("competing")
	}
	switch in.Source {
	case "none":
		add("no_point")
	case "typed":
		add("typed_point")
	case "device":
		switch {
		case in.AccuracyM > policy.ConfirmM:
			add("accuracy_poor")
		case in.AccuracyM > policy.GoodM:
			add("accuracy_fair")
		}
		if in.SpreadM > policy.GoodM {
			add("unstable")
		}
		if now.Sub(in.CapturedAt) > policy.MaxAge {
			add("stale_capture")
		}
		if in.CapturedAt.Sub(now) > policy.ClockSkew {
			add("clock_skew")
		}
	}
	if in.Point != nil {
		if st.Placed {
			m := float64(StraightMeters(st.At, *in.Point))
			d.DisplacementM = &m
			if m > policy.LargeMoveM {
				add("large_move")
			}
		}
		if st.DistrictCentre != nil && float64(StraightMeters(*st.DistrictCentre, *in.Point)) > policy.FarFromDistrictM {
			add("far_from_district")
		}
	}
	d.Flags = flags
	if len(flags) == 0 && in.Kind == "new" && in.Target == "school" && in.Source == "device" {
		d.Status = CaptureAccepted
	} else {
		d.Status = CapturePending
	}
	return d
}

// ReviewMessage is why the reader may not decide the capture, or "".
func ReviewMessage(reviewer, reporter, status, decision, note string) string {
	switch {
	case status != CapturePending:
		return "This report has already been decided."
	case reviewer == reporter:
		return "Someone else must review your own report."
	case decision != "approve" && decision != "reject":
		return "Choose approve or reject."
	case decision == "reject" && strings.TrimSpace(note) == "":
		return "Say why the report is rejected."
	case len([]rune(strings.TrimSpace(note))) > noteMaxRunes:
		return fmt.Sprintf("Keep the note under %d characters.", noteMaxRunes)
	}
	return ""
}
