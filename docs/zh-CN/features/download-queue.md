---
icon: lucide/circle-pause
---

# 下载队列

所有下载任务都会进入 **Queue** 页面：正在下载的任务显示在 **In progress**，等待空闲名额的任务显示在 **Waiting**，已完成的任务显示在 **Done**，失败的任务显示在 **Failed**。同时下载的歌曲数量由[并行下载](download-settings.md#parallel-downloads)设置控制。

## 其他账户的下载

每个账户的队列只包含自己的下载；管理员的队列包含所有人的下载。在管理员的队列中，别人请求的歌曲会在标题下显示是谁请求的，没有人请求的歌曲（[播放列表监控](playlist-monitor.md)或重试添加的）显示为“自动添加”。列表上方的 **Remove others'**（仅管理员可见）会一次性把这些全部移出管理员的队列：等待中的不会开始，正在下载的会为请求它的账户完成，但不会再出现在管理员的页面上。

在别处（另一台设备、另一个账户或 **Clear queue**）被移出队列的歌曲，会在下次刷新时离开列表，而不会一直停在 **In progress**。

## 暂停与继续

Queue 页面顶部的 **Pause downloads** 会阻止队列启动新任务。在更改设置、排查问题，或长队列等待期间需要重启/更新 Castify 时，此功能很有用。

- 已经开始的下载会正常完成，不会被取消。在这些任务完成前，页面会显示 **Pausing downloads…** 和剩余任务数。
- 随后页面会显示 **Downloads paused**：在恢复前不会启动新下载。等待中的歌曲仍按原顺序排队，并显示为 **Paused**；侧边栏的 Queue 徽标会变为灰色。
- 点击 **Resume downloads** 后，等待中的歌曲会按照当时的设置和[音频来源顺序](download-settings.md#audio-provider)继续下载。
- 队列暂停期间添加的歌曲也会排队等待。移除等待中的歌曲或点击 **Clear queue** 后，该歌曲不会启动下载。
- [Playlist Monitor](playlist-monitor.md) 在每首曲目开始前也会等待；[Replace Audio](replace-audio.md) 任务同样如此。
- 新的监控检查和对账扫描会等待后再开始。播客监控会在剧集之间暂停；手动下载剧集也会等待。正在进行的工作会正常完成。
- Library improvement 会使用其原生暂停机制，并完成当前曲目。全局队列恢复后，需要在原有页面中单独继续 improvement。新任务和崩溃恢复也会遵守全局暂停状态。

所有人都可以看到队列是否暂停，但只有管理员可以暂停或恢复队列，因为队列包含所有人的下载任务。

同一全局控制也位于 Settings → Downloads & files（`/settings/files`）页面顶部，以及 Playlist Monitor（`/monitor`）的 Check all 旁边。两处都会读取服务器已确认的状态。操作需要管理员 Web 会话；配对手机令牌不具备服务器管理权限。如果未收到确认，请先使用 Check status 检查状态，再发送下一次更改。

## 重启或更新

队列会在重启、崩溃或容器更新后保留。下次启动时，等待中的歌曲以及 Castify 停止时正在下载的歌曲（会从头开始）都会重新排队；暂停状态也会恢复。因此，长队列可按以下步骤处理：

1. 点击 **Pause downloads**，并等待页面显示 **Downloads paused**。
2. 重启或更新 Castify，完成所需更改。
3. 点击 **Resume downloads**。

重启后，如果播放列表中的歌曲下载完成，其 [M3U](m3u-export.md) 和 Navidrome 播放列表会像原始下载完成时一样刷新一次。

::: info 不会保留的内容

- 已完成和失败的歌曲：重启后队列只会列出仍待处理的任务。
- [Replace Audio](replace-audio.md) 任务：需要再次替换歌曲。
- 在[仅媒体库模式](library-only.md)下不会启动下载：已保存的歌曲会等待退出该模式后再开始。
  :::

## API

[`GET /api/queue/state`](../api-reference.md#get-apiqueuestate)、[`POST /api/queue/pause`](../api-reference.md#post-apiqueuepause) 和 [`POST /api/queue/resume`](../api-reference.md#post-apiqueueresume)；每次状态变化也会通过 [WebSocket](../api-reference.md#websocket) 帧 `queue_state` 广播。
