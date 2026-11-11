/**
 * Build-time additions to app.json. A development build (EXPO_PUBLIC_EDIFY_ENV
 * "development") talks to the developer's own machine over plain HTTP
 * (localhost, or 10.0.2.2 from the Android emulator), which an Android
 * release build refuses unless allowed. Only a development build is given
 * that; staging and production builds keep HTTPS only, and
 * src/config/environment.ts refuses plain HTTP to anything but this machine.
 */
const { withAndroidManifest } = require('expo/config-plugins');

function withDevelopmentCleartext(config) {
  return withAndroidManifest(config, (next) => {
    const application = next.modResults.manifest.application?.[0];
    if (application) {
      application.$['android:usesCleartextTraffic'] = 'true';
    }
    return next;
  });
}

module.exports = ({ config }) =>
  process.env.EXPO_PUBLIC_EDIFY_ENV === 'development' ? withDevelopmentCleartext(config) : config;
