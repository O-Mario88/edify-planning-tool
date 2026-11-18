package pagegate

import (
	"context"
	"testing"
)

func TestTheDesktopReadingIsCarriedOnTheContext(t *testing.T) {
	if Desktop(context.Background()) {
		t.Error("a request that says nothing is the phone app's reading")
	}
	if !Desktop(WithDesktop(context.Background(), true)) {
		t.Error("a desktop request is not read as one")
	}
	if Desktop(WithDesktop(context.Background(), false)) {
		t.Error("a phone request is read as a desktop one")
	}
}
