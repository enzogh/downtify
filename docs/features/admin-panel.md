---
icon: lucide/shield
---

# Admin panel

Admins have their own panel, **Admin** (`/admin`), in the side bar under the pages and in the **More** sheet on a phone. It opens on an overview of the server and of how it is used, and holds every setting that is the server's rather than one person's. **Settings** (`/settings`) keeps what is yours: your account, how the app looks and plays, the apps and **About**.

Older links to the server's settings (`/settings/users`, `/settings/sources`…) open the same section of the panel. The panel is hidden in **User view** and from users who aren't admins: going to `/admin` opens Settings instead.

## Overview

The first page reads the [listening history](recommendations.md#listening-history) of every account, over the last 7, 30 or 90 days:

| Part | What it shows |
|------|---------------|
| Figures | **Plays** (and listening time), **Listeners** (accounts that played something, out of all accounts), **Songs on the server** (artists and size on disk) and **Downloads in progress** (with the failed ones). Each opens where it is managed: Activity, Users, [Storage](storage-usage.md), the [queue](download-queue.md). |
| Plays per day | Every day of the period, the busiest day full height. Hover a day for its plays and listening time. Below: the share of plays skipped and of songs streamed without being downloaded. |
| Most played | The ten artists and ten songs played most, with how many people played each. Skips aren't counted. |
| Who listens | Each account's plays, listening time, share of skips and last play. |
| Playing right now | What each signed-in browser or app is playing, updated every 30 seconds. |
| Latest plays | Everyone's last plays, a skipped or streamed one marked as such. |
| Manage | Shortcuts to Users, Activity, Storage, Doctor, Audio sources and Server. |

The figures come from [`GET /api/admin/listening`](../api-reference.md#get-apiadminlistening).

## Sections

After the overview, in the order an admin reaches for them: **Users**, **Activity**, **Audio sources**, **Downloads & files**, **Tags & lyrics**, **Library** (with [library-only mode](library-only.md), moved here from General), **Navidrome**, **Doctor**, **Notifications** and **Server**. They work as they did under Settings, with the same **Save** bar.
