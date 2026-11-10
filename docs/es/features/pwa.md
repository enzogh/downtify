---
icon: lucide/smartphone
---

# Instalar como app (PWA)

La interfaz web de Castify es una Progressive Web App: tanto en iOS como en Android puedes añadirla a la pantalla de inicio y se abre a pantalla completa, como una app nativa, sin barra de direcciones ni controles del navegador.

## iOS (Safari)

1. Abre Castify en Safari
2. Pulsa el botón **Compartir**
3. Pulsa **Añadir a pantalla de inicio**

El icono de Castify aparece en tu pantalla de inicio y se abre en su propia ventana.

## Android (Chrome)

1. Abre Castify en Chrome
2. Pulsa el menú **⋮**
3. Pulsa **Añadir a la pantalla de inicio** (o **Instalar aplicación**, si Chrome la ofrece directamente)

## La guía de instalación

En un teléfono, Castify muestra una breve guía poco después de abrir la página, mientras se ejecute en una pestaña del navegador y no desde la pantalla de inicio. Los pasos se adaptan al navegador: Safari, otro navegador de iOS, un navegador dentro de una app (ábrelo primero en Safari) o Android, donde un solo botón **Instalar la app** abre el diálogo de instalación de Chrome cuando lo ofrece.

**Más tarde** la oculta durante un día; vuelve hasta que la app esté instalada. **Listo, ya está instalada** la detiene en ese navegador. El menú de la cuenta (avatar, arriba a la derecha) mantiene una entrada **Instalar la app** para reabrirla. Los ordenadores nunca la ven.

## Cómo funciona

`frontend/index.html` enlaza un [web app manifest](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest) (`/manifest.json`) que establece `"display": "standalone"` y `start_url: "/"`, además de los iconos que Android usa para el acceso directo de la pantalla de inicio y el selector de apps. Es lo que Chrome/Android lee para instalar la app a pantalla completa y con su propio icono.

Safari en iOS no lee los campos `display` ni los de iconos del manifest al usar «Añadir a pantalla de inicio»: necesita sus propias etiquetas `<meta>`/`<link>` `apple-mobile-web-app-capable` y `apple-touch-icon` en `index.html`, que se definen junto al manifest para que ambas plataformas tengan el mismo comportamiento independiente, a pantalla completa y con el icono de Castify.

Un service worker (`/sw.js`) guarda la propia app en el dispositivo: la app instalada se abre sin conexión y reproduce las listas y álbumes que guardaste en él — consulta [Escuchar sin conexión](offline.md). Todo lo demás necesita el servidor, así que el resto de la app no puede cargarse sin conexión.
