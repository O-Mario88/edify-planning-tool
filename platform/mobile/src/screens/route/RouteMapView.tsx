/**
 * The route map in the app: the keyless map page (routeMapHtml) in a
 * WebView. The app hands it the pins; a tapped pin comes back by id.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentType, Ref } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';
import { WebView } from 'react-native-webview';

import { fonts } from '../../theme';
import { mapHtml } from './routeMapHtml';
import type { MapScene } from './routeMapHtml';

/** The WebView props the map uses (the library's own typing collapses to
 * never under this React Native; these are its documented props). */
interface MapWebViewHandle {
  injectJavaScript: (script: string) => void;
}
interface MapWebViewProps {
  ref?: Ref<MapWebViewHandle>;
  source: { html: string; baseUrl: string };
  originWhitelist: string[];
  onMessage: (event: { nativeEvent: { data: string } }) => void;
  javaScriptEnabled: boolean;
  scrollEnabled: boolean;
  style: StyleProp<ViewStyle>;
}
const MapWebView = WebView as unknown as ComponentType<MapWebViewProps>;

export interface RouteMapViewProps {
  readonly scene: MapScene;
  readonly onSelect: (id: string) => void;
}

export function RouteMapView({ scene, onSelect }: RouteMapViewProps) {
  const ref = useRef<MapWebViewHandle>(null);
  const [isReady, setIsReady] = useState(false);
  const [hasFailed, setHasFailed] = useState(false);
  const html = useMemo(() => mapHtml(), []);
  const latest = useRef(scene);

  // The page asks for the scene each time it (re)loads; a new scene is sent as it comes.
  const send = (next: MapScene) => ref.current?.injectJavaScript(`window.edifyRender(${JSON.stringify(JSON.stringify(next))}); true;`);
  useEffect(() => {
    latest.current = scene;
    if (isReady) send(scene);
  }, [isReady, scene]);

  function handleMessage(event: { nativeEvent: { data: string } }) {
    let message: { type?: string; id?: string } = {};
    try {
      message = JSON.parse(event.nativeEvent.data);
    } catch {
      return;
    }
    if (message.type === 'ready') {
      setIsReady(true);
      send(latest.current);
    }
    if (message.type === 'failed') setHasFailed(true);
    if (message.type === 'select' && message.id) onSelect(message.id);
  }

  return (
    <View style={styles.box} accessibilityLabel="Route map">
      <MapWebView
        ref={ref}
        source={{ html, baseUrl: 'https://localhost/' }}
        originWhitelist={['https://*']}
        onMessage={handleMessage}
        javaScriptEnabled
        scrollEnabled={false}
        style={styles.web}
      />
      {hasFailed ? <Text style={styles.note}>The map could not load. Your route is in List View.</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { flex: 1, overflow: 'hidden' },
  web: { flex: 1, backgroundColor: '#eef2f3' },
  note: { position: 'absolute', bottom: 8, left: 8, right: 8, fontFamily: fonts.medium, fontSize: 13, textAlign: 'center' },
});
