/**
 * The route map in the app's web build: the same keyless map page in a
 * same-origin frame (WebView is native only).
 */
import { createElement, useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { mapHtml } from './routeMapHtml';
import type { RouteMapViewProps } from './RouteMapView';

type MapFrame = HTMLIFrameElement & { contentWindow: (Window & { edifyRender?: (json: string) => void }) | null };

export function RouteMapView({ scene, onSelect }: RouteMapViewProps) {
  const frame = useRef<MapFrame | null>(null);
  const [isReady, setIsReady] = useState(false);
  const html = useMemo(() => mapHtml(), []);
  const select = useRef(onSelect);
  const latest = useRef(scene);
  useEffect(() => {
    select.current = onSelect;
    latest.current = scene;
  });

  useEffect(() => {
    function handle(event: MessageEvent) {
      if (event.source !== frame.current?.contentWindow || typeof event.data !== 'string') return;
      try {
        const message = JSON.parse(event.data) as { type?: string; id?: string };
        if (message.type === 'ready') {
          setIsReady(true);
          frame.current?.contentWindow?.edifyRender?.(JSON.stringify(latest.current));
        }
        if (message.type === 'select' && message.id) select.current(message.id);
      } catch {
        /* not ours */
      }
    }
    window.addEventListener('message', handle);
    return () => window.removeEventListener('message', handle);
  }, []);

  useEffect(() => {
    if (isReady) frame.current?.contentWindow?.edifyRender?.(JSON.stringify(scene));
  }, [isReady, scene]);

  return (
    <View style={styles.box} accessibilityLabel="Route map">
      {createElement('iframe', { ref: frame, srcDoc: html, title: 'Route map', style: { border: 0, width: '100%', height: '100%' } })}
    </View>
  );
}

const styles = StyleSheet.create({ box: { flex: 1, overflow: 'hidden' } });
