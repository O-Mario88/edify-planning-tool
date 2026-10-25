package app.edifyplanning.mobile;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.os.Build;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

/**
 * The app's one screen: Capacitor's web view, with Edify's own native plugins
 * registered on it (the Android side of EdifyBridgeViewController.swift).
 */
public class MainActivity extends BridgeActivity {

    /** apps.notifications.fcm.ANDROID_CHANNEL, and static/js/native-push.js. */
    static final String CHANNEL = "edify";

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Registered before super.onCreate, which starts the bridge.
        registerPlugin(EdifySettingsPlugin.class);
        registerPlugin(EdifyChromePlugin.class);
        super.onCreate(savedInstanceState);
        createNotificationChannel();
    }

    /**
     * "Edify notifications", there from the first launch, so a notification
     * never lands in Android's "Miscellaneous" channel and the phone's settings
     * for Edify always show it. High importance shows it as a banner. What a
     * locked phone shows is set on each notification, not here (only the
     * system may set a channel's lock-screen visibility): the server marks
     * every one private (apps.notifications.fcm). Android keeps whatever a
     * person has since chosen for an existing channel, so this changes nothing
     * after the first time.
     */
    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return; // no channels before Android 8
        NotificationChannel channel = new NotificationChannel(
            CHANNEL,
            "Edify notifications",
            NotificationManager.IMPORTANCE_HIGH
        );
        channel.setDescription("Work that needs you in Edify");
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.createNotificationChannel(channel);
    }
}
