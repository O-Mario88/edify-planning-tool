package routeplan

import (
	"testing"
	"time"
)

func TestDecideGPSCapture_AllPolicies(t *testing.T) {
	now := time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC)
	mukono := LatLng{Lat: 0.3533, Lng: 32.7553}
	nearMukono := LatLng{Lat: 0.3540, Lng: 32.7560} // ~110 m away
	farKampala := LatLng{Lat: 0.3136, Lng: 32.5811} // ~19.8 km away

	t.Run("first capture by CCEO with good accuracy (12m) saves directly", func(t *testing.T) {
		d := DecideGPSCapture(CaptureInput{
			Target: "school", Kind: "new", Source: "device",
			Point: &mukono, AccuracyM: 12, CapturedAt: now.Add(-15 * time.Second), BaseVersion: 0,
		}, SchoolState{Placed: false, Version: 0, DistrictCentre: &mukono}, "CCEO", now, DefaultPolicy)
		if d.Status != CaptureAccepted {
			t.Fatalf("expected CaptureAccepted, got %s (flags=%v)", d.Status, d.Flags)
		}
	})

	t.Run("normal update within 1000m and rural 35m tolerance saves directly", func(t *testing.T) {
		d := DecideGPSCapture(CaptureInput{
			Target: "school", Kind: "correction", Source: "device",
			Point: &nearMukono, AccuracyM: 35, CapturedAt: now.Add(-20 * time.Second), BaseVersion: 1,
		}, SchoolState{Placed: true, At: mukono, Version: 1, DistrictCentre: &mukono}, "CCEO", now, DefaultPolicy)
		if d.Status != CaptureAccepted {
			t.Fatalf("expected normal authorized update to save directly, got %s (flags=%v)", d.Status, d.Flags)
		}
		if d.DisplacementM == nil || *d.DisplacementM < 50 || *d.DisplacementM > 300 {
			t.Fatalf("unexpected displacement %v", d.DisplacementM)
		}
	})

	t.Run("large displacement (>1000m) flags large_move and holds for verification", func(t *testing.T) {
		d := DecideGPSCapture(CaptureInput{
			Target: "school", Kind: "correction", Source: "device",
			Point: &farKampala, AccuracyM: 10, CapturedAt: now.Add(-10 * time.Second), BaseVersion: 1,
		}, SchoolState{Placed: true, At: mukono, Version: 1, DistrictCentre: &mukono}, "CCEO", now, DefaultPolicy)
		if d.Status != CapturePending {
			t.Fatalf("expected CapturePending for large move, got %s", d.Status)
		}
	})

	t.Run("poor accuracy (>50m) flags accuracy_poor and holds for review", func(t *testing.T) {
		d := DecideGPSCapture(CaptureInput{
			Target: "school", Kind: "new", Source: "device",
			Point: &mukono, AccuracyM: 85, CapturedAt: now.Add(-10 * time.Second), BaseVersion: 0,
		}, SchoolState{Placed: false, Version: 0, DistrictCentre: &mukono}, "CCEO", now, DefaultPolicy)
		if d.Status != CapturePending {
			t.Fatalf("expected CapturePending for poor accuracy 85m, got %s", d.Status)
		}
	})

	t.Run("version conflict prevents silent overwrite", func(t *testing.T) {
		d := DecideGPSCapture(CaptureInput{
			Target: "school", Kind: "correction", Source: "device",
			Point: &nearMukono, AccuracyM: 10, CapturedAt: now.Add(-10 * time.Second), BaseVersion: 1,
		}, SchoolState{Placed: true, At: mukono, Version: 2, DistrictCentre: &mukono}, "CCEO", now, DefaultPolicy)
		if d.Status != CapturePending {
			t.Fatalf("expected version conflict not to auto-accept, got %s", d.Status)
		}
	})

	t.Run("partner field officer capture requires supervisor review", func(t *testing.T) {
		d := DecideGPSCapture(CaptureInput{
			Target: "school", Kind: "new", Source: "device",
			Point: &mukono, AccuracyM: 10, CapturedAt: now.Add(-10 * time.Second), BaseVersion: 0,
		}, SchoolState{Placed: false, Version: 0, DistrictCentre: &mukono}, "PartnerFieldOfficer", now, DefaultPolicy)
		if d.Status != CapturePending {
			t.Fatalf("expected partner capture to queue for review, got %s", d.Status)
		}
	})

	t.Run("Guarded ClearCache invalidates cached routes immediately", func(t *testing.T) {
		r := &countingRouter{}
		g := Guard(r, 100, func() time.Time { return now })
		pts := []LatLng{mukono, nearMukono}
		_, _ = g.Matrix(t.Context(), pts)
		_, _ = g.Matrix(t.Context(), pts)
		if r.calls.Load() != 1 {
			t.Fatalf("expected 1 cached call, got %d", r.calls.Load())
		}
		g.ClearCache()
		_, _ = g.Matrix(t.Context(), pts)
		if r.calls.Load() != 2 {
			t.Fatalf("expected ClearCache to force fresh route call (2), got %d", r.calls.Load())
		}
	})
}
