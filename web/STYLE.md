# Style guide

Read this before any UI change. Update it when you add a page, a token, or a shared partial.

## Where styles live

| File | Owns |
| --- | --- |
| `web/templates/_theme.html` | Design tokens (`--frost-*`, `--ink-*`, `--btn-*`), `--glass` / `--chrome-inset` per viewport, `.glass-stage`, `.glass-card`, `.glass-wait` |
| `web/templates/_cover_layout.html` | Cover-photo page layout (`.pjt-stage`, title, mark, lead, big buttons, `--pjt-*` sizes) plus the decode-then-blur script. Used by project home and Ichiban Kuji |
| `web/templates/_admin_chrome.html` | Top-right Login (guests) or Admin dropdown + username pill (logged in), centered Home, top-left `.back-btn` |
| `web/templates/_overlay.html` | Shared `.glass-overlay` CSS, change-password panel, open/close script |
| `web/templates/_stage_bg.html` | Full-screen `<picture>` background + white fade (slideshow, lottery). Set `bg_desktop` / `bg_mobile` before including |
| `web/templates/_progress_veil.html` | Upload pie overlay |
| `web/static/style.css` | Base form controls, admin cards, `.btn` defaults, `.flash`. Do not put page layout here (cached) |
| `web/static/profile.css` | Nickname modal |
| `config/appsetting.py` | Look knobs read as `cfg.*` (fades, button colors, glass padding) |

`_theme.html` is included by `base.html` (all pages that extend it) and directly by `slideshow.html` / `lottery.html`. Everything that needs `cfg` lives in a Jinja partial, not in a static CSS file.

## Viewport split

- Mobile `@media (max-width: 640px)`, desktop `@media (min-width: 641px)`. Nothing in between.
- Size knobs (font size, padding, gaps, mark size) live only in those two blocks. Shared layout stays outside `@media`.
- When a request is about size, spacing, type, or images and does not say which, ask 手機 or 桌機 first and edit only that block.
- Cover photos are always `<picture>` with a `(max-width: 640px)` source so only one JPEG downloads. Missing side falls back to the other.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#f4efe6` cream | Page background (style.css) |
| `--ink` | `#1c1915` | Body text |
| `--muted` | `#6b6459` | Labels, meta |
| `--card` | `#fffcf7` | Admin cards, inputs |
| `--line` | `#ddd4c6` | Card and input borders |
| `--err` | `#9f1239` | Danger button, error flash |
| `--frost-fill` | `rgba(255,255,255,0.42)` | Glass fill once blur is on |
| `--frost-solid` | `rgba(255,255,255,0.72)` | Glass fill before the cover decodes |
| `--frost-line` | `rgba(255,255,255,0.55)` | Glass and pill border |
| `--frost-shadow` | `0 8px 32px rgba(28,25,21,0.08)` | Glass and pill shadow |
| `--frost-blur` | `blur(28px) saturate(180%)` | `backdrop-filter` |
| `--ink-fade` | ink at `1 - BUTTON_TEXT_FADE` | Button and pill labels (bold) |
| `--ink-soft` | `rgba(28,25,21,0.48)` | Text on glass (slideshow name/note, progress label) |
| `--btn-upload` | `UPLOAD_BTN_COLOR` `#f4efe6` at `1 - BUTTON_FADE` | Big button: upload |
| `--btn-slideshow` | `SLIDESHOW_BTN_COLOR` `#d4d1cc` | Big button: slideshow, secondary |
| `--btn-lottery` | `LOTTERY_BTN_COLOR` gold `#d4af37` | Big button: lottery, Ichiban Kuji |
| `--glass` | 2cm desktop / 1cm mobile (`GLASS_PAD_CM`, `GLASS_PAD_MOBILE_CM`) | Inset of the stage glass |
| `--chrome-inset` | same as `--glass` | Left/right of Back and Admin pills |

Gold pie / sparkle accent: `#d4af37`, pale gold `#ffe9b0`, silver `#d8dde3`.

Fonts: body `"PingFang TC", "Noto Sans TC", sans-serif`. Project title on cover pages uses the script stack `"Snell Roundhand", "Savoye LET", "Segoe Script", "Apple Chancery", "Kaiti TC", "STKaiti", "KaiTi", cursive` at weight 400 and `1 - TITLE_FADE` opacity.

## Building blocks

### Glass stage

```html
<div class="glass-stage my-stage">
  <div class="glass-card">
    <div class="glass-body">…</div>
  </div>
  {% include "_credit.html" %}
</div>
```

- `.glass-stage`: fixed full viewport, grid rows `minmax(0, 1fr) auto`, gap 0.1cm, padding `var(--glass)`, top padding at least 64px (room for the chrome pills). `@ChalmersProduction` sits 0.1cm under the glass.
- `.glass-card`: radius 28px, frost fill/border/shadow/blur. Pages only add `display`, `padding`, and `overflow` (`auto` for forms, `hidden` + inner scroll for the admin list).
- `.glass-body`: centered column, `width: min(720px, 100%)` (login uses 360px).
- The cover glass scrolls (`overflow: auto`) when its buttons do not fit (for example four admin buttons at 1280×800).
- Cover pages put `.glass-wait` on the stage wrapper. The glass stays `--frost-solid` without blur until the background `img.decode()` resolves, then JS adds `.is-ready` (Safari samples an empty layer otherwise).

### Buttons

- Big cover buttons (`.pjt-stage .btn`): full width inside `.actions`, bold `--ink-fade` label, 1px white border, `white-space: pre-line` for leftover newlines. Fill: default `--btn-upload`, `.secondary` `--btn-slideshow`, `.lottery` `--btn-lottery`. Sizes come from `--pjt-btn-*` (desktop 18px / `22px 20px` / radius 16; mobile 16px / `16px 14px` / radius 14).
- Chrome pills (`.back-btn`, `.chrome-home`, `.chrome-end .admin-btn`): frost fill + border, `8px 14px`, 14px bold `--ink-fade`, radius 999px, `top: 12px`. Back left, Home centered (hidden on `/`), Admin/Login right, inset `--chrome-inset`. Back is `msg.lottery_back` to the project home. Guests see Login (`/admin/login`, hidden on the login page). After login the username pill opens 中文 / English, 改密碼, 登出. Staff also get the Admin `.chrome-drop`: 帳號管理 (`/admin/accounts`, root) and 專案管理 (`/admin`). Guest-only accounts do not see Admin.
- Admin list: `.btn` (ink), `.btn.secondary` (card), `.btn.small`, `.btn.danger.delete-project` (~70% size). Logout uses the pill look, min-height 44px, `appearance: none`.
- Destructive actions use the in-page confirm pattern: a `.delete-arm` with an arm button and a hidden `.delete-confirm` form (「確認」/「取消」). Do not use `window.confirm` (the lottery reset is the one legacy exception).

### Overlays

- Progress veil: fixed, inset 2cm, frost glass, gold pie. Show with `.is-on` only (never an unscoped `display: grid`, it beats `hidden`).
- Full-screen dim for previews: `rgba(28,25,21,0.82)`, click to close.
- Modal card (nickname): `#fffcf7`, radius 16px, `rgba(28,25,21,0.55)` backdrop. Guests pick 中文 / English (`.lang-pick`) before the name; submit reloads so the page follows that language.
- Glass panel overlays (Ichiban Kuji `.kuji-panel`, create/password `.glass-overlay` in `_overlay.html`): fixed, inset `var(--glass)` (top at least 64px), `rgba(28,25,21,0.28)` backdrop, `.glass-card` inside, scroll inside the card, close pill top-right of the card. Below the chrome (z-index 20 vs 30) so Back and Admin stay usable. While a panel is open, `body.panel-open` hides the page glass so it does not blur through as a smudge. Create-project overlay lives on `/admin`; create-account overlay lives on `/admin/accounts`. Title-row `+` (`.add-btn`) opens the matching overlay.
- Anything with a `[hidden]` state and its own `display` needs `[hidden] { display: none !important; }`.

### Backgrounds

- `<picture>` covering the viewport with `object-fit: cover`, then a white `.stage-fade` / `.pjt-fade` overlay at `BKG_FADE` / `PJT_FADE` opacity.
- Photos are always `object-fit: contain`, centered, `max-width/max-height: 100%` inside a `minmax(0, 1fr)` frame. Never `width/height: 100%` on a photo.
- Photo corners: 22px; shadow `box-shadow`, not `filter: drop-shadow`.

### Copy

- All user-facing strings live in `config/msg.py` as `(zh, en)` tuples. `msg.foo` follows `g.lang`. Use `msg.zh.foo` / `msg.en.foo` when a template needs both. Guest language is `device_lang:{id}` (first-visit modal); login accounts default `zh` and switch on `/admin/accounts` or the username menu.
- Multi-line strings need `white-space: pre-line`. In JS use `{{ msg.x | tojson }}`. HTML attributes collapse `\n`, so use `&#10;` there.

## Pages

| Page | Template | Layout |
| --- | --- | --- |
| Site landing `/` | `index.html` | Cream glass stage. Title 「專案 / Projects」 then project links. Empty copy differs for logged-in vs guest. Create project/account is not on this page |
| Project home `/p/<slug>/` | `project_home.html` + `_cover_layout.html` | `pjt-*` cover photo, `.glass-wait` glass with script title, optional `pjt-mark`, lead, big buttons: 上傳照片 (upload) / 輪播照片 (secondary) / 一番賞 (lottery gold) / 抽獎 (lottery gold, any project role including guest) / 闖關任務 (logged-in only, gold; guests enter via QR) |
| Challenge rooms `/p/<slug>/challenge/` | `challenge_rooms.html` + `_cover_layout.html` | Host only (logged-in). Same cover as home. Gold 「創建房間」 opens a `_overlay.html` glass panel (name, 4-digit PIN, 單人/多人). At most 5 live (`lobby`/`running`) rooms; the button hides at the cap. Room cards below with enter + in-page delete (not while running). 「遊玩歷史」 is a closed `<details>`. `body.panel-open` hides `.pjt-ui` so the cover glass does not smudge through. Guests hitting this URL go to the PIN join page |
| Challenge room `/p/<slug>/challenge/rooms/<id>` | `challenge_landing.html` + `_cover_layout.html` | Host interior: room name, large PIN, room QR (`/challenge/join?pin=`), waiting avatars, 開始挑戰 (always in lobby; gray/disabled until 等待中 is 0 and at least one player is ready) then that room’s god view, 清空挑戰者 (lobby only). Back goes to the room list |
| Challenge join `/p/<slug>/challenge/join` | `challenge_join.html` | Cream glass. Title 闖關任務 + 4-digit PIN. Room QR (`?pin=`) joins that lobby (leaves any other live seat on this device). No pin and already in a live room → play |
| Challenge play `/p/<slug>/challenge/play` | `challenge_play.html` | Cream glass. Lobby: waiting count, floating circular avatars; own chip shows 「點擊照片及名稱可更換」 until Ready (tap photo to replace, tap name to rename; photo/name carry into the next room until 清除闖關任務). 準備完成. After start: timer + score on one bar, refresh line, then task cards. Each card: points on the left (`{n}分` white bold on a pill: high `--err`, mid gold `#d4af37`, low `--muted`), then band + status pill, prompt, and actions on their own row (上傳 / 驗收 / 刷新). High/mid keep 刷新 after pass (spend a refresh to swap the task; score from the old pass stays, another pass adds again). High tasks show labeled 原圖 / 上傳 thumbs to the right of the prompt (56px mobile / 64px desktop, cover in a 16px-radius square); click to preview, empty slot if missing. Refresh / low-rotate pulses the card gold once. Passed prompts dim with a ✓. 完成 at the bottom. Task type 18px mobile / 20px desktop. Back/Home/Admin hidden until the session is settled. No player (kicked or never joined) redirects to join |
| Challenge god `/p/<slug>/challenge/rooms/<id>/god` | `challenge_god.html` | Desktop 2×2 panes for that room (any logged-in). Back/Home/Admin hidden. Quest type: points 22/26px, band 22px, title 26px, status 24px, 認可 24px, ✓ 44px (2×). Points (`{n}分`) sit on the left of each card as a white-bold pill (high `--err`, mid gold `#d4af37`, low `--muted`). Status (完成 / 未完成) sits to the right of the band as a white-label pill: passed green `#2f7d4a`, open `--muted`, failed `--err`. Band color: high `--err`, mid gold `#d4af37`, low `--muted`. High tasks show 原圖 / 上傳 thumbs to the right of the title, left of 通過／認可: fixed square (`--god-thumb` 72/80px) with `object-fit: cover`, 16px radius, overflow clipped so every JPEG is the same size. Click to preview; empty slot if missing. Mid/low uploads still show a single 上傳 thumb. When a task’s prompt / target / color changes (high/mid refresh or low rotate), the card pulses gold once. 認可 on low stays gray/disabled until the challenger taps 驗收 (`awaiting_host`); Pass/Reject on photo tasks. Passed titles dim; thumbs stay in color. Preview JPEG is `object-fit: contain` within 90vw/90vh (grid `min-height: auto` would overflow). Settle at the cross. Empty slots gray |
| Challenge results `/p/<slug>/challenge/results/<id>` | `challenge_results.html` | Cream glass. Bar chart grows on load; avatar on top of each bar (nickname letter if no photo) |
| Upload `/p/<slug>/upload` | `upload.html` | Cream glass stage, left-aligned bilingual labels, centered submit, Back pill, progress veil |
| Slideshow `/p/<slug>/slideshow` | `slideshow.html` | Dark page. `wall`: `bkg-*` background, name glass above, photo (22px corners, 2cm inset), note glass below. `full`: cream letterbox, photo only, 64px top pad for chrome. Bottom-right `.ss-zoom` pill (same frost as Back) toggles zoom: hide Back/Home/Admin, reclaim chrome pad, `requestFullscreen`. Same button or Escape exits zoom; a second Escape leaves to project home. Chrome and Zoom fade after 5s idle |
| Lottery `/p/<slug>/lottery` (admin) | `lottery.html` | `lot-*` background, 3D sphere, sparkles canvas, winner contain-and-center inset `LOTTERY_PAD_CM`, side thumbs, gold pill 「再抽一位」, white bold 「重置抽獎」 bottom-left |
| Ichiban Kuji `/p/<slug>/kuji` | `kuji.html` + `_cover_layout.html` | Same cover layout as home with `kuji-*` background (falls back to `pjt-*`) and `kuji-mark`. Lead, then a hint that person photos add draws up to the cap, then chance line (root: unlimited copy, no cap). Buttons: 查看獎品狀態 (secondary) / 抽一番賞 (lottery gold) / 我的獎品 (upload). Glass panel overlays for status, tear, and my prizes. Prize card is a grid: `.prize-art` (`minmax(0,1fr)`, img centered, `max-width/max-height: var(--kuji-prize-fit)`) then the name row so the JPEG cannot cover the title or get clipped by the ticket. Mobile `--kuji-prize-fit` 72%, desktop 80%. Default ticket is a red/gold 籤卡 (double gold frame, 一番賞 mark, left 米線, serial from the draw id); uploaded ticket art still gets that chrome overlay. Mobile `--kuji-grade-size` 22px, desktop 48px. After a tear, 「再抽一次」 (gold pill) shows when `me.left > 0`. Sparkles canvas lives in `.tear-scene` (`pointer-events: none`), not over the panel buttons |
| Admin login `/admin/login` | `admin_login.html` | Cream glass stage, 360px body |
| Admin projects `/admin` | `admin.html` | Cream glass stage, scroll inside the glass. Title row: `+` (if `can_create_project`) opens 新增專案 overlay, then 「管理專案」. Project `<details>` cards. After 「更多」: 「刪除專案」 (if allowed), then five collapsed blocks (重置／清除 / 首頁 / 輪播 / 抽獎 / 一番賞). 「重置／清除」 lists 重置照片、重置抽獎、重置一番賞、清除遊戲歷史、清除闖關任務, each with purpose copy and in-page confirm. 一番賞 A–E cards keep the grade title; each has 中文名稱 and 英文名稱 (empty = `{grade}賞` / `Prize {grade}`). 2-col asset grid (1 col on mobile). Logout pill above the credit |
| Admin accounts `/admin/accounts` | `admin_accounts.html` | Same glass stage as `/admin`. Root only. Title row: `+` opens 新增帳號 overlay, then 「管理帳號」. Root has a lang-only card. Other accounts: language, per-project role, reset password, delete |

## New-page checklist

1. Extend `base.html` (gets `_theme.html`, chrome, credit, nickname modal). Full-screen dark pages include `_theme.html` and `_admin_chrome.html` themselves.
2. Use `.glass-stage` + `.glass-card` (or `_cover_layout.html` for a cover-photo page). Do not copy the frost values; use the tokens.
3. Back pill top-left to project home, Admin pill top-right, credit 0.1cm under the glass.
4. Background photos as desktop/mobile assets in `store.ASSETS`, rendered with `<picture>`.
5. Size knobs only in the mobile / desktop blocks.
6. Strings in `config/msg.py` as `(zh, en)` tuples, `pre-line` when a side still has a newline.
7. Screenshot at 390px and 1280px wide before calling it done.
