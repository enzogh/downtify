---
icon: lucide/smartphone
---

# Telepítés alkalmazásként (PWA)

A Castify webes felülete Progressive Web App: iOS-en és Androidon is hozzáadhatod a kezdőképernyőhöz, és teljes képernyőn indul, mint egy natív alkalmazás, címsor és böngészőelemek nélkül.

## iOS (Safari)

1. Nyisd meg a Castifyt Safariban
2. Koppints a **Megosztás** gombra
3. Koppints a **Főképernyőhöz adás** lehetőségre

A Castify ikonja megjelenik a kezdőképernyőn, és önálló ablakban indul.

## Android (Chrome)

1. Nyisd meg a Castifyt Chrome-ban
2. Koppints a **⋮** menüre
3. Koppints a **Hozzáadás a kezdőképernyőhöz** lehetőségre (vagy az **Alkalmazás telepítése** lehetőségre, ha a Chrome közvetlenül felkínálja)

## A telepítési útmutató

Telefonon a Castify röviddel az oldal betöltése után rövid útmutatót mutat, amíg böngészőlapon fut, nem a kezdőképernyőről. A lépések a böngészőhöz igazodnak: Safari, másik iOS-böngésző, alkalmazáson belüli böngésző (először nyisd meg Safariban) vagy Android, ahol egyetlen **Alkalmazás telepítése** gomb nyitja meg a Chrome telepítőablakát, ha a Chrome felajánlja.

A **Később** egy napra elrejti; visszatér, amíg az app nincs telepítve. A **Kész, telepítve** leállítja abban a böngészőben. A fiókmenü (avatar, jobb felül) megtart egy **Alkalmazás telepítése** bejegyzést az újranyitáshoz. Számítógépen sosem jelenik meg.

## Hogyan működik

A `frontend/index.html` egy [web app manifestre](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest) (`/manifest.json`) hivatkozik, amely beállítja a `"display": "standalone"` és a `start_url: "/"` értéket, valamint az ikonokat, amelyeket az Android a kezdőképernyő-parancsikonhoz és az alkalmazásváltóhoz használ. Ezt olvassa a Chrome/Android, hogy az alkalmazást teljes képernyősen, saját ikonnal telepítse.

Az iOS Safari a „Főképernyőhöz adás” során egyáltalán nem olvassa a manifest `display` és ikonmezőit — saját `apple-mobile-web-app-capable` és `apple-touch-icon` `<meta>`/`<link>` címkékre van szüksége az `index.html`-ben, amelyeket a manifest mellett állítunk be, hogy mindkét platform ugyanazt az önálló, teljes képernyős viselkedést kapja a Castify ikonjával.

Nincs offline támogatás vagy service worker — a Castify felülete csak addig hasznos, amíg eléri a hozzá tartozó backendet, ezért ez egy „telepíthető, teljes képernyős webalkalmazás”, nem offline is működő.
