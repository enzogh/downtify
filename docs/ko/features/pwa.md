---
icon: lucide/smartphone
---

# 앱으로 설치(PWA)

Castify의 웹 UI는 Progressive Web App입니다. iOS와 Android 모두에서 홈 화면에 추가할 수 있으며, 주소 표시줄이나 브라우저 탐색 UI 없이 네이티브 앱처럼 전체 화면으로 실행됩니다.

## iOS (Safari)

1. Safari에서 Castify를 엽니다
2. **공유** 버튼을 탭합니다
3. **홈 화면에 추가**를 탭합니다

Castify 아이콘이 홈 화면에 나타나고 독립된 창으로 실행됩니다.

## Android (Chrome)

1. Chrome에서 Castify를 엽니다
2. **⋮** 메뉴를 탭합니다
3. **홈 화면에 추가**를 탭합니다(Chrome이 바로 제안하면 **앱 설치**)

## 설치 안내

휴대폰에서 페이지가 홈 화면이 아닌 브라우저 탭에서 열려 있으면, Castify는 로드 직후 짧은 안내를 표시합니다. 단계는 브라우저에 맞춰 바뀝니다: Safari, 다른 iOS 브라우저, 앱 내 브라우저(먼저 Safari에서 열기), 또는 Android — Chrome이 제공하면 **앱 설치** 버튼 하나로 Chrome 설치 창이 열립니다.

**나중에**를 누르면 하루 동안 숨겨지고, 앱이 설치될 때까지 다시 나타납니다. **완료, 설치했어요**를 누르면 해당 브라우저에서 더 이상 표시되지 않습니다. 계정 메뉴(오른쪽 위 아바타)의 **앱 설치** 항목으로 다시 열 수 있습니다. 컴퓨터에서는 표시되지 않습니다.

## 작동 방식

`frontend/index.html`은 `"display": "standalone"`과 `start_url: "/"`를 지정하는 [웹 앱 매니페스트](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest)(`/manifest.json`)를 연결하며, Android가 홈 화면 바로가기와 앱 전환기에 쓰는 아이콘도 함께 지정합니다. Chrome/Android는 이를 읽어 앱을 전체 화면과 고유 아이콘으로 설치합니다.

iOS Safari는 "홈 화면에 추가"를 할 때 매니페스트의 `display`나 아이콘 필드를 전혀 읽지 않습니다. `index.html`에 자체 `apple-mobile-web-app-capable`, `apple-touch-icon` `<meta>`/`<link>` 태그가 필요하며, 이 태그를 매니페스트와 함께 설정해 두 플랫폼 모두 Castify 아이콘과 함께 같은 독립 전체 화면 동작을 얻도록 했습니다.

서비스 워커(`/sw.js`)가 앱 자체를 기기에 보관해요. 설치한 앱은 연결 없이도 열리고, 기기에 저장한 플레이리스트와 앨범을 재생해요 — [오프라인 듣기](offline.md)를 참고하세요. 그 밖의 모든 것은 서버가 필요하므로, 오프라인일 때는 앱의 나머지 부분을 불러올 수 없어요.
