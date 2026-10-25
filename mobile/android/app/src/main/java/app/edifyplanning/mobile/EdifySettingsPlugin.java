package app.edifyplanning.mobile;

import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Edify's notification settings on the phone, called from
 * static/js/native-push.js as `EdifySettings`. The iPhone has the same plugin
 * (EdifyBridgeViewController.swift); `pushReady` is Android's alone.
 */
@CapacitorPlugin(name = "EdifySettings")
public class EdifySettingsPlugin extends Plugin {

    private static final String NOT_OPENED = "The phone's notification settings could not be opened.";

    /**
     * Opens Edify's own page in the phone's notification settings. The phone's
     * setting is the one switch for Edify's notifications
     * (docs/push-notifications.md), so "Open phone settings" lands there.
     */
    @PluginMethod
    public void openNotificationSettings(PluginCall call) {
        Context context = getContext();
        String app = context.getPackageName();
        Intent notifications = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, app)
            : appInfo(app);
        if (open(notifications) || open(appInfo(app))) {
            call.resolve();
        } else {
            call.reject(NOT_OPENED);
        }
    }

    /**
     * Whether this build can receive notifications: an Android build reaches
     * Firebase only when it was built with google-services.json, whose plugin
     * adds the `google_app_id` resource. Without it Firebase is not set up, and
     * asking it for a token would close the app, so the page asks this first.
     */
    @PluginMethod
    public void pushReady(PluginCall call) {
        Context context = getContext();
        int firebase = context.getResources().getIdentifier("google_app_id", "string", context.getPackageName());
        JSObject result = new JSObject();
        result.put("ready", firebase != 0);
        call.resolve(result);
    }

    private static Intent appInfo(String app) {
        return new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", app, null));
    }

    private boolean open(Intent intent) {
        try {
            getActivity().startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException e) {
            return false;
        }
    }
}
