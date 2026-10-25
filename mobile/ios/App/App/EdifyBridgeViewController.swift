import Capacitor
import UIKit

/// The app's one screen: Capacitor's web view, with Edify's own native
/// plugins registered on it (SceneDelegate makes it the window's root).
class EdifyBridgeViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(EdifySettingsPlugin())
    }
}

/// Opens Edify's own page in the phone's notification settings. The phone's
/// setting is the one switch for Edify's notifications (docs/push-notifications.md),
/// so the page's "Open phone settings" lands exactly there, not on Settings'
/// first screen, where the generic `app-settings:` link can leave a person.
/// Called from static/js/native-push.js as `EdifySettings.openNotificationSettings()`.
@objc(EdifySettingsPlugin)
public class EdifySettingsPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "EdifySettingsPlugin"
    public let jsName = "EdifySettings"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "openNotificationSettings", returnType: CAPPluginReturnPromise)
    ]

    @objc func openNotificationSettings(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            // Edify's notification settings from iOS 16; before that, Edify's
            // page in Settings, one tap from them.
            let address: String
            if #available(iOS 16.0, *) {
                address = UIApplication.openNotificationSettingsURLString
            } else {
                address = UIApplication.openSettingsURLString
            }
            guard let url = URL(string: address) else {
                call.reject("The phone's notification settings could not be opened.")
                return
            }
            UIApplication.shared.open(url) { opened in
                if opened {
                    call.resolve()
                } else {
                    call.reject("The phone's notification settings could not be opened.")
                }
            }
        }
    }
}
