package app.edifyplanning.mobile;

import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;
import android.os.Build;
import android.view.View;
import android.view.Window;
import androidx.annotation.NonNull;
import androidx.core.graphics.ColorUtils;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.regex.Pattern;

/**
 * The phone's status bar and gesture bar take the colours of the page beside
 * them, as on an iPhone, where the page itself runs under both bars. Called
 * from static/js/system-chrome.js as `EdifyChrome.setBars({top, bottom})`.
 *
 * From Android 15 an app cannot paint its status bar a colour; what shows
 * behind the bars is the window behind the web view. Where the phone's web
 * view is new enough, Capacitor runs the page under the bars and the page's
 * own safe-area padding shows there (as on iOS); on an older web view it
 * shrinks the page to fit between them, and these two colours fill the strips.
 */
@CapacitorPlugin(name = "EdifyChrome")
public class EdifyChromePlugin extends Plugin {

    private static final Pattern HEX = Pattern.compile("^#[0-9a-fA-F]{6}$");

    private Integer top;
    private Integer bottom;

    @PluginMethod
    public void setBars(PluginCall call) {
        Integer topColor = colour(call.getString("top"));
        Integer bottomColor = colour(call.getString("bottom"));
        if (topColor == null || bottomColor == null) {
            call.reject("Bar colours are written #rrggbb.");
            return;
        }
        top = topColor;
        bottom = bottomColor;
        getBridge().executeOnMainThread(() -> {
            paint();
            call.resolve();
        });
    }

    /**
     * Capacitor's own system-bars handling resets the window's background when
     * the configuration changes (a rotation, dark mode); the page's colours go
     * back on once it has.
     */
    @Override
    protected void handleOnConfigurationChanged(Configuration newConfig) {
        super.handleOnConfigurationChanged(newConfig);
        if (top == null) return;
        View decor = getActivity().getWindow().getDecorView();
        decor.post(this::paint);
    }

    private void paint() {
        if (top == null || bottom == null) return;
        Window window = getActivity().getWindow();
        View decor = window.getDecorView();
        decor.setBackground(new Bands(top, bottom));
        // A new background resets the window's padding, which is how Capacitor
        // keeps the page between the bars on an older web view: asking for the
        // insets again has Capacitor put its padding back.
        ViewCompat.requestApplyInsets(decor);
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            // Before Android 15 the bars are painted in a colour of their own,
            // over the window behind them.
            window.setStatusBarColor(top);
            window.setNavigationBarColor(bottom);
        }
        WindowInsetsControllerCompat bars = WindowCompat.getInsetsController(window, decor);
        // "Light" bars are a light background: their icons are drawn dark.
        bars.setAppearanceLightStatusBars(isLight(top));
        bars.setAppearanceLightNavigationBars(isLight(bottom));
    }

    private static Integer colour(String hex) {
        if (hex == null || !HEX.matcher(hex).matches()) return null;
        return 0xFF000000 | Integer.parseInt(hex.substring(1), 16);
    }

    private static boolean isLight(int colour) {
        return ColorUtils.calculateLuminance(colour) > 0.5;
    }

    /** The window's background: the top half one colour, the bottom half another. */
    private static final class Bands extends Drawable {

        private final Paint topPaint = new Paint();
        private final Paint bottomPaint = new Paint();

        Bands(int top, int bottom) {
            topPaint.setColor(top);
            bottomPaint.setColor(bottom);
        }

        @Override
        public void draw(@NonNull Canvas canvas) {
            Rect area = getBounds();
            int middle = area.centerY();
            canvas.drawRect(area.left, area.top, area.right, middle, topPaint);
            canvas.drawRect(area.left, middle, area.right, area.bottom, bottomPaint);
        }

        @Override
        public void setAlpha(int alpha) {
            // Always opaque.
        }

        @Override
        public void setColorFilter(ColorFilter colorFilter) {
            // Not tinted.
        }

        @Override
        public int getOpacity() {
            return PixelFormat.OPAQUE;
        }
    }
}
