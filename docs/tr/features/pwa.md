---
icon: lucide/smartphone
---

# Uygulama olarak yükle (PWA)

Castify’ın web arayüzü bir Progressive Web App’tir: hem iOS’ta hem Android’de ana ekranınıza ekleyebilirsiniz; adres çubuğu ve tarayıcı denetimleri olmadan, yerel bir uygulama gibi tam ekran açılır.

## iOS (Safari)

1. Castify’ı Safari’de açın
2. **Paylaş** düğmesine dokunun
3. **Ana Ekrana Ekle**’ye dokunun

Castify simgesi ana ekranınızda belirir ve bağımsız bir pencerede açılır.

## Android (Chrome)

1. Castify’ı Chrome’da açın
2. **⋮** menüsüne dokunun
3. **Ana ekrana ekle**’ye dokunun (Chrome doğrudan sunuyorsa **Uygulamayı yükle**)

## Kurulum rehberi

Telefonda Castify, sayfa ana ekrandan değil bir tarayıcı sekmesinde açıldığı sürece, yüklendikten kısa süre sonra kısa bir rehber gösterir. Adımlar tarayıcıya göre değişir: Safari, başka bir iOS tarayıcısı, uygulama içi tarayıcı (önce Safari’de açın) veya Android; Android’de Chrome sunduğunda tek bir **Uygulamayı yükle** düğmesi Chrome’un kurulum penceresini açar.

**Sonra** rehberi bir gün gizler; uygulama yüklenene kadar geri gelir. **Tamam, yüklendi** onu o tarayıcıda durdurur. Hesap menüsü (avatar, sağ üst) yeniden açmak için **Uygulamayı yükle** girişini tutar. Bilgisayarlar onu hiç görmez.

## Nasıl çalışır

`frontend/index.html`, `"display": "standalone"` ve `start_url: "/"` değerlerini belirleyen bir [web app manifest](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest) dosyasına (`/manifest.json`) bağlanır; ayrıca Android’in ana ekran kısayolu ve uygulama değiştirici için kullandığı simgeleri içerir. Chrome/Android uygulamayı tam ekran ve kendi simgesiyle yüklemek için bunu okur.

iOS Safari, “Ana Ekrana Ekle” için manifest’teki `display` veya simge alanlarını hiç okumaz — `index.html` içinde kendi `apple-mobile-web-app-capable` ve `apple-touch-icon` `<meta>`/`<link>` etiketlerine ihtiyaç duyar. Bunlar manifest ile birlikte ayarlanır; böylece iki platform da Castify simgesiyle aynı bağımsız, tam ekran davranışını alır.

Çevrimdışı destek ya da service worker yoktur — Castify arayüzü yalnızca eşleştiği arka uca ulaşabildiği sürece işe yarar; yani bu “yüklenebilir, tam ekran bir web uygulaması”dır, çevrimdışı çalışan bir uygulama değil.
