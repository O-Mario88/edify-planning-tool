package pagegate

import "context"

type desktopKey struct{}
type djangoAbsentKey struct{}

// WithDesktop marks ctx as a page read for a desktop browser (the web app,
// GetPageRequest.desktop) rather than for the phone app.
func WithDesktop(ctx context.Context, desktop bool) context.Context {
	return context.WithValue(ctx, desktopKey{}, desktop)
}

// WithDjangoAbsent marks ctx as running with no existing Django application
// configured (EDIFY_EXISTING_APP_URL == ""), so pages render natively instead
// of handing off to an absent upstream for lazy-seeding or hybrid edge cases.
func WithDjangoAbsent(ctx context.Context, absent bool) context.Context {
	return context.WithValue(ctx, djangoAbsentKey{}, absent)
}

// DjangoAbsent reports whether the gateway is serving with Django absent.
func DjangoAbsent(ctx context.Context) bool {
	absent, _ := ctx.Value(djangoAbsentKey{}).(bool)
	return absent
}

// Desktop is whether the page is read as a desktop browser draws it. A page
// whose desktop and phone versions differ (the role dashboards, To-Do, IA
// Analytics: their mobile-role-home header, mobile-home-only and
// mobile-home-hide parts) hands a desktop reading on to the existing page
// until it builds the desktop parts itself; every other page reads the same
// either way.
func Desktop(ctx context.Context) bool {
	desktop, _ := ctx.Value(desktopKey{}).(bool)
	return desktop
}
