---
icon: lucide/smartphone
---

# Als App installieren (PWA)

Die Weboberfläche von Castify ist eine Progressive Web App: Sowohl unter iOS als auch unter Android kannst du sie zum Home-Bildschirm hinzufügen. Sie startet dann im Vollbild wie eine native App, ohne Adressleiste und Browser-Bedienelemente.

## iOS (Safari)

1. Öffne Castify in Safari
2. Tippe auf die Schaltfläche **Teilen**
3. Tippe auf **Zum Home-Bildschirm**

Das Castify-Symbol erscheint auf dem Home-Bildschirm und startet in einem eigenen Fenster.

## Android (Chrome)

1. Öffne Castify in Chrome
2. Tippe auf das Menü **⋮**
3. Tippe auf **Zum Startbildschirm hinzufügen** (oder **App installieren**, falls Chrome das direkt anbietet)

## Die Installationsanleitung

Auf dem Handy zeigt Castify kurz nach dem Laden eine kleine Anleitung, solange die Seite in einem Browser-Tab läuft und nicht vom Home-Bildschirm. Die Schritte passen sich dem Browser an: Safari, ein anderer iOS-Browser, ein In-App-Browser (zuerst in Safari öffnen) oder Android, wo ein einziger Button **App installieren** Chromes Installationsdialog öffnet, wenn Chrome ihn anbietet.

**Später** blendet sie für einen Tag aus; sie kommt wieder, bis die App installiert ist. **Fertig, sie ist installiert** beendet sie in diesem Browser. Das Kontomenü (Avatar, oben rechts) behält einen Eintrag **App installieren**, um sie erneut zu öffnen. Computer sehen sie nie.

## So funktioniert es

`frontend/index.html` verweist auf ein [Web-App-Manifest](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest) (`/manifest.json`), das `"display": "standalone"` und `start_url: "/"` festlegt, dazu die Symbole, die Android für die Verknüpfung auf dem Startbildschirm und den App-Umschalter nutzt. Das liest Chrome/Android, um die App im Vollbild und mit eigenem Symbol zu installieren.

iOS-Safari liest für „Zum Home-Bildschirm“ weder das Feld `display` noch die Symbolfelder des Manifests — er braucht eigene `<meta>`-/`<link>`-Tags (`apple-mobile-web-app-capable` und `apple-touch-icon`) in `index.html`. Sie werden zusammen mit dem Manifest gesetzt, damit beide Plattformen dasselbe eigenständige Vollbildverhalten mit dem Castify-Symbol bekommen.

Ein Service Worker (`/sw.js`) behält die App selbst auf dem Gerät: Die installierte App öffnet sich ohne Verbindung und spielt die Playlists und Alben, die du darauf gespeichert hast — siehe [Offline hören](offline.md). Alles andere braucht den Server, daher kann der Rest der App offline nicht laden.
