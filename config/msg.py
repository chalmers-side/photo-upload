# User-facing copy as (zh, en). msg.foo follows the request language.
# Use msg.zh.foo / msg.en.foo when both sides are needed in one template.

LANGS = ("zh", "en")


def normalize_lang(value):
    v = (value or "").strip().lower()
    if v in ("en", "english"):
        return "en"
    return "zh"


def get_lang():
    try:
        from flask import g, has_request_context

        if has_request_context():
            return normalize_lang(getattr(g, "lang", None))
    except Exception:
        pass
    return "zh"


def pick(pair, lang=None):
    lang = normalize_lang(lang or get_lang())
    if isinstance(pair, str):
        return pair
    zh, en = pair
    return en if lang == "en" else zh


class _Bundle:
    def __init__(self, lang):
        self._lang = lang

    def __getattr__(self, name):
        try:
            return pick(_STRINGS[name], self._lang)
        except KeyError:
            raise AttributeError(name) from None


zh = _Bundle("zh")
en = _Bundle("en")

# Language-specific fallbacks used when saving both prize names at once.
kuji_grade_zh = "{grade}賞"
kuji_grade_en = "Prize {grade}"
site_credit = "@ChalmersProduction"

_STRINGS = {
    # Shared chrome
    "admin": ("管理", "Admin"),
    "site_title": ("照片", "Photos"),
    "nav_home": ("首頁", "Home"),
    "lang_label": ("語系", "Language"),
    "lang_zh": ("中文", "中文"),
    "lang_en": ("English", "English"),
    "lang_saved": ("已更新語系", "Language updated"),
    # Site landing (/)
    "home_lead": (
        "用專案連結上傳或輪播。管理請走右上角。",
        "Use a project link to upload or play the slideshow. Admin is at the top right.",
    ),
    "home_empty_guest": (
        "用專案連結進入後，這裡會出現你去過的專案。",
        "After you open a project link, it will show up here.",
    ),
    "home_empty_user": ("還沒有被指派的專案。", "No projects assigned yet."),
    "add_menu": ("新增", "Add"),
    "new_account": ("新增管理帳號", "New account"),
    "password_new": ("新密碼", "New password"),
    "password_again": ("再輸入一次", "Confirm password"),
    "password_old": ("目前密碼", "Current password"),
    "password_change": ("改密碼", "Change password"),
    "password_changed": ("已更新密碼", "Password updated"),
    "password_reset": ("重置密碼", "Reset password"),
    "password_mismatch": ("兩次密碼不相同", "Passwords do not match"),
    "wrong_password": ("目前密碼不正確", "Current password is wrong"),
    "bad_username": (
        "帳號請用 1–32 字的英文、數字、底線或連字號",
        "Username: 1–32 letters, numbers, _ or -",
    ),
    "bad_password": ("密碼請設 4–72 字", "Password must be 4–72 characters"),
    "username_taken": ("這個帳號已被使用", "This username is already taken"),
    "user_missing": ("帳號不存在", "Account not found"),
    "user_created": ("已建立帳號「{name}」", "Created account “{name}”"),
    "user_deleted": ("已刪除帳號「{name}」", "Deleted account “{name}”"),
    "cannot_delete_root": ("不能刪除 root", "Cannot delete root"),
    "cannot_assign_root": ("root 不需指派專案", "Root is not assigned per project"),
    "bad_role": ("不支援的角色", "Unknown role"),
    "roles_saved": ("已更新「{name}」的專案權限", "Updated project roles for “{name}”"),
    "admin_accounts": ("管理帳號", "Accounts"),
    "admin_projects": ("管理專案", "Projects"),
    "no_accounts": ("還沒有帳號。", "No accounts yet."),
    "role_none": ("（未指派）", "(none)"),
    "role_admin": ("admin", "admin"),
    "role_maintainer": ("maintainer", "maintainer"),
    "role_guest": ("guest", "guest"),
    "delete_user": ("刪除帳號", "Delete account"),
    "staff_only": ("沒有管理權限", "You do not have admin access"),
    "close_panel": ("關閉", "Close"),
    # Nickname modal
    "nickname_title": ("怎麼稱呼你？", "What should we call you?"),
    "nickname_lead": (
        "第一次使用請留下稱呼，並選擇語言。輪播和抽獎會顯示這個名字。",
        "First visit: enter a name and pick a language.\nIt shows in the slideshow and lottery.",
    ),
    "nickname_placeholder": ("例如 小明", "e.g. Alex"),
    "nickname_ok": ("確定", "OK"),
    "nickname_bad": ("請輸入 1–20 字的稱呼", "Enter a name (1–20 characters)"),
    "nickname_save_failed": ("無法儲存稱呼", "Could not save name"),
    # Project home
    "project_home_lead": (
        "開始分享今天的照片吧～\n會有小驚喜唷！",
        "Start sharing your photos～\nThere will be a surprise！",
    ),
    "upload_photos": ("上傳照片", "Upload photos"),
    "play_slideshow": ("輪播照片", "Slideshow"),
    "lottery": ("抽獎", "Lottery"),
    # Upload
    "upload_title": ("上傳照片", "Upload photos"),
    "upload_page_title": ("上傳 · {name}", "Upload · {name}"),
    "photo_label": ("照片（每次最多 5 張）", "Photos (up to 5 at a time)"),
    "caption_label": ("請為照片下一個註解", "Write a note for this photo (optional)"),
    "caption_placeholder": ("請輸入一段話", "Enter some words for this photo"),
    "upload_submit": ("上傳", "Upload"),
    "upload_notice": (
        "照片會用於輪播。\n若有其他人入鏡，請先徵得同意。",
        "Photos appear in the slideshow.\nIf others are in them, please get their consent.",
    ),
    "upload_progress": ("上傳中…", "Uploading…"),
    "upload_processing": ("處理照片中…", "Processing photos…"),
    "upload_failed": ("上傳失敗", "Upload failed"),
    "need_photo": ("請選擇照片", "Please choose a photo"),
    "upload_too_many": ("一次最多 5 張", "Up to 5 photos at a time"),
    "caption_too_long": ("文字太長（最多 500 字）", "Caption is too long (max 500 characters)"),
    "bad_image": (
        "無法讀取這張圖片，請改用 JPG / PNG / HEIC",
        "Could not read this image. Try JPG / PNG / HEIC.",
    ),
    "empty_file": ("沒有讀到檔案", "No file received"),
    "upload_checking": (
        "已上傳 {n} 張，正在確認照片中是否有人物…",
        "Uploaded {n} photo(s). Checking for people…",
    ),
    "upload_person_ok": (
        "{n} 張有人物：抽獎機會 +{n}（累計 {chances} 次），一番賞剩餘 {kuji} 次（上限 {cap} 次）",
        "{n} photo(s) with people: lottery +{n} (total {chances}), {kuji} Ichiban Kuji draw(s) left (cap {cap})",
    ),
    "upload_person_capped": (
        "{n} 張有人物。抽獎機會上限 {max} 次，以最新 {max} 張為主；一番賞剩餘 {kuji} 次（上限 {cap} 次）",
        "{n} photo(s) with people. Lottery chances cap at {max} (your latest {max} count); {kuji} Ichiban Kuji draw(s) left (cap {cap})",
    ),
    "upload_person_none": (
        "{n} 張未偵測到人物：照片仍會輪播，但不列入抽獎與一番賞",
        "{n} photo(s) without people: they still play in the slideshow but do not count for the lottery or Ichiban Kuji",
    ),
    "upload_check_slow": (
        "照片仍在確認中，稍後可到一番賞頁查看次數",
        "Still checking. See your draws on the Ichiban Kuji page later",
    ),
    # Slideshow
    "slideshow_title": ("輪播 · {name}", "Slideshow · {name}"),
    "slideshow_leave": ("離開", "Leave"),
    "no_photos": ("尚無照片", "No photos yet"),
    "slideshow_credit": ("{name}：{caption}", "{name}: {caption}"),
    "guest_name": ("這位朋友", "Friend"),
    "slideshow_zoom": ("放大", "Zoom in"),
    "slideshow_zoom_out": ("還原", "Zoom out"),
    # Lottery
    "lottery_title": ("抽獎 · {name}", "Lottery · {name}"),
    "lottery_ready": ("準備抽獎…", "Drawing…"),
    "lottery_failed": ("抽獎失敗", "Draw failed"),
    "lottery_empty": ("目前沒有可抽獎的照片", "No photos available to draw"),
    "lottery_winner": (
        "恭喜 {name} 中獎，共上傳了 {n} 張照片",
        "Congratulations {name}, {n} photo(s) uploaded",
    ),
    "lottery_back": ("返回", "Back"),
    "lottery_again": ("再抽一位", "Draw again"),
    # Ichiban Kuji
    "kuji": ("一番賞", "Ichiban Kuji"),
    "kuji_title": ("一番賞 · {name}", "Ichiban Kuji · {name}"),
    "kuji_lead": (
        "上傳一張有人物的照片就能抽一次一番賞",
        "Each photo with people earns one Ichiban Kuji draw",
    ),
    "kuji_hint": (
        "上傳有人物的照片可增加抽獎次數，每人最多 {n} 次",
        "Photos with people add draws, up to {n} per person",
    ),
    "kuji_hint_unlimited": ("root 可不限次數抽一番賞", "Root can draw without a cap"),
    "kuji_chances": ("剩餘 {n} 次可抽", "{n} draw(s) left"),
    "kuji_chances_unlimited": ("不限次數", "Unlimited draws"),
    "kuji_chances_pending": (
        "剩餘 {n} 次可抽（{pending} 張照片確認中）",
        "{n} draw(s) left ({pending} photo(s) being checked)",
    ),
    "kuji_btn_status": ("查看獎品狀態", "Prize status"),
    "kuji_btn_draw": ("抽一番賞", "Draw a ticket"),
    "kuji_btn_mine": ("我的獎品", "My prizes"),
    "kuji_again": ("再抽一次", "Draw again"),
    "kuji_close": ("關閉", "Close"),
    "kuji_grade": ("{grade}賞", "Prize {grade}"),
    "kuji_label_zh": ("中文名稱", "Chinese name"),
    "kuji_label_en": ("英文名稱", "English name"),
    "kuji_label_too_long": ("獎品名稱最多 40 字", "Prize name is at most 40 characters"),
    "kuji_left": ("剩 {left} / {total}", "{left} of {total} left"),
    "kuji_gone": ("已抽出", "Gone"),
    "kuji_tear_hint": ("按住左下角往右拉開", "Hold the bottom-left corner and drag right"),
    "kuji_win": ("恭喜抽中 {name}！", "You won {name}!"),
    "kuji_mine_empty": ("還沒有抽中的獎品", "No prizes yet"),
    "kuji_claim": ("領獎", "Claim"),
    "kuji_claim_lead": (
        "請將此畫面出示給工作人員，由工作人員按下確認。\n確認後無法再次領取。",
        "Show this screen to the staff and let them tap Confirm.\nIt cannot be claimed again.",
    ),
    "kuji_claimed": ("已領取 · {time}", "Claimed · {time}"),
    "kuji_sold_out": ("獎品已全部抽完", "All prizes are gone"),
    "kuji_cap_reached": (
        "每人最多抽 {n} 次，已經用完了",
        "You have used all {n} draws",
    ),
    "kuji_pending": (
        "照片確認中，請稍候再抽",
        "Your photos are still being checked. Try again shortly",
    ),
    "kuji_need_photo": (
        "上傳一張有人物的照片即可抽一次",
        "Upload a photo with people to earn a draw",
    ),
    "kuji_claim_missing": ("找不到這筆獎品", "Prize not found"),
    "kuji_already_claimed": ("這個獎品已經領過了", "This prize was already claimed"),
    "kuji_failed": ("操作失敗，請再試一次", "Something went wrong. Please try again"),
    "kuji_not_ready": ("尚未設定獎品", "No prizes set up yet"),
    # Admin login
    "admin_login_title": ("管理登入", "Admin login"),
    "logout": ("登出", "Log out"),
    "login": ("登入", "Login"),
    "username": ("帳號", "Username"),
    "password": ("密碼", "Password"),
    "login_failed": ("帳號或密碼錯誤", "Wrong username or password"),
    # Admin projects
    "projects": ("專案", "Projects"),
    "new_project": ("新增子專案", "New project"),
    "project_name": ("名稱", "Name"),
    "project_name_placeholder": ("例如 婚禮", "e.g. Wedding"),
    "project_slug": ("URL slug（可留空）", "URL slug (optional)"),
    "project_add": ("新增", "Add"),
    "delete_project": ("刪除專案", "Delete project"),
    "reset_photos": ("重置照片", "Reset photos"),
    "reset_photos_ok": ("已清除「{name}」的上傳照片", "Cleared uploaded photos for “{name}”"),
    "delete_confirm": ("確認", "Confirm"),
    "delete_cancel": ("取消", "Cancel"),
    "project_more": ("更多", "More"),
    "no_projects": ("還沒有專案。", "No projects yet."),
    "open_project": ("前往專案", "Open project"),
    "project_url": ("專案", "Project"),
    "upload_url": ("上傳", "Upload"),
    "slideshow_url": ("輪播", "Slideshow"),
    "copy_url": ("複製連結", "Copy link"),
    "copied_url": ("已複製", "Copied"),
    "qr_open": ("QR code", "QR code"),
    "qr_download": ("下載 QR", "Download QR"),
    "qr_close": ("關閉", "Close"),
    "project_meta": ("slug: {slug} · 照片 {count}", "slug: {slug} · {count} photos"),
    "project_created": ("已建立「{name}」", "Created “{name}”"),
    "project_deleted": (
        "已刪除「{name}」（含 URL、Redis 與照片）",
        "Deleted “{name}” (URLs, Redis, and photos)",
    ),
    "confirm_delete_all": (
        "會刪除這個專案，包含 URL、Redis 與照片。確定？",
        "This deletes the project, including URLs, Redis, and photos. Continue?",
    ),
    "need_project_name": ("請輸入專案名稱", "Please enter a project name"),
    "bad_slug": (
        "slug 只能用小寫英文、數字與連字號",
        "Slug may only use lowercase letters, numbers, and hyphens",
    ),
    "slug_taken": ("這個 URL slug 已被使用", "This URL slug is already in use"),
    "project_missing": ("專案不存在", "Project not found"),
    "asset_pjt_mark": ("首頁縮圖", "Home mark"),
    "asset_pjt_desktop": ("首頁背景(桌面)", "Home background (desktop)"),
    "asset_pjt_mobile": ("首頁背景(手機)", "Home background (mobile)"),
    "asset_bkg_desktop": ("輪播背景(桌面)", "Slideshow background (desktop)"),
    "asset_bkg_mobile": ("輪播背景(手機)", "Slideshow background (mobile)"),
    "asset_lot_desktop": ("抽獎背景(桌面)", "Lottery background (desktop)"),
    "asset_lot_mobile": ("抽獎背景(手機)", "Lottery background (mobile)"),
    "asset_upload": ("上傳", "Upload"),
    "asset_delete": ("刪除", "Delete"),
    "asset_saved": ("已更新專案圖片", "Project image updated"),
    "asset_removed": ("已刪除專案圖片", "Project image deleted"),
    "bad_asset": ("不支援的圖片類型", "Unknown image type"),
    "admin_sec_home": ("首頁", "Home"),
    "admin_sec_slideshow": ("輪播", "Slideshow"),
    "admin_sec_lottery": ("抽獎", "Lottery"),
    "admin_sec_kuji": ("一番賞", "Ichiban Kuji"),
    "admin_sec_reset": ("重置／清除", "Reset / clear"),
    "reset_photos_hint": (
        "刪除賓客上傳的照片、抽獎券與輪播快取。專案圖片會留著。",
        "Deletes guest photos, lottery tickets, and the slideshow cache. Project images stay.",
    ),
    "reset_lottery_hint": (
        "清除中獎名單，所有裝置可再抽。照片不會刪。",
        "Clears lottery winners so every device can be drawn again. Photos stay.",
    ),
    "kuji_reset_hint": (
        "清除一番賞抽獎紀錄，獎項數量恢復未抽。",
        "Clears Ichiban Kuji draws so prize counts go back to undrawn.",
    ),
    "challenge_history_wipe": ("清除遊戲歷史", "Clear play history"),
    "challenge_history_wipe_hint": (
        "刪除已結束的闖關紀錄。進行中與等待中的房間不受影響。",
        "Deletes finished quest records. Live and waiting rooms stay.",
    ),
    "challenge_history_wiped": (
        "已清除「{name}」的闖關歷史",
        "Cleared play history for “{name}”",
    ),
    "challenge_wipe_hint": (
        "刪除所有闖關房間（含進行中）、闖關任務照片，以及大廳頭貼與稱呼。",
        "Deletes every quest room, including live ones, task photos, and lobby names/avatars.",
    ),
    "settings_title": ("參數設定", "Settings"),
    "settings_save": ("保存", "Save"),
    "settings_saved": ("已保存專案參數", "Project settings saved"),
    "bad_setting": ("參數超出範圍", "Setting is out of range"),
    "set_slideshow_mode": ("輪播模式", "Slideshow mode"),
    "slideshow_mode_wall": ("留言牆", "Message wall"),
    "slideshow_mode_full": ("滿版", "Full screen"),
    "set_slideshow_interval": ("輪播每張停留秒數", "Seconds each slideshow photo stays"),
    "set_slideshow_fade": ("輪播交叉淡化秒數", "Slideshow crossfade seconds"),
    "set_slideshow_queue_max": ("輪播 queue 最多張數", "Slideshow queue max photos"),
    "set_slideshow_per_device": (
        "超過 queue 上限時，每裝置只播最新幾張",
        "Newest photos per device when over queue max",
    ),
    "set_lottery_sphere_max": ("抽獎球體照片數", "Photos on the lottery sphere"),
    "set_lottery_seconds": ("抽獎球體旋轉秒數", "Lottery spin seconds"),
    "reset_lottery": ("重置抽獎", "Reset lottery"),
    "confirm_reset_lottery": (
        "會清除中獎紀錄，所有裝置可再抽。照片不會刪。確定？",
        "This clears lottery winners so every device can be drawn again. Photos stay. Continue?",
    ),
    "lottery_reset": ("已重置「{name}」的抽獎中獎紀錄", "Reset lottery winners for “{name}”"),
    "kuji_admin_meta": ("總數 {total} · 剩餘 {left}", "Total {total} · {left} left"),
    "kuji_per_user_label": ("每人最多可抽次數", "Max draws per device"),
    "kuji_count_label": ("數量", "Count"),
    "kuji_admin_drawn": ("已抽 {drawn} / {total}", "Drawn {drawn} of {total}"),
    "asset_kuji_mark": ("一番賞縮圖", "Kuji mark"),
    "asset_kuji_ticket": ("一番賞票券", "Kuji ticket"),
    "asset_kuji_desktop": ("一番賞背景(桌面)", "Kuji background (desktop)"),
    "asset_kuji_mobile": ("一番賞背景(手機)", "Kuji background (mobile)"),
    "kuji_saved": ("已保存一番賞設定", "Ichiban Kuji settings saved"),
    "kuji_reset_btn": ("重置一番賞", "Reset Ichiban Kuji"),
    "kuji_reset_ok": ("已重置「{name}」的一番賞紀錄", "Reset Ichiban Kuji for “{name}”"),
    "kuji_total_below_drawn": (
        "{grade}賞數量不能少於已抽出數量",
        "Prize {grade} count cannot be below the number already drawn",
    ),
    "upload_consent_label": (
        "是否願意提供照片於主辦方使用（必選）",
        "May the host use this photo? (required)",
    ),
    "upload_consent_yes": ("願意", "Yes"),
    "upload_consent_no": ("不願意", "No"),
    "upload_need_consent": (
        "請選擇是否願意提供照片於主辦方使用",
        "Please choose whether the host may use this photo",
    ),
    "challenge": ("闖關任務", "Quest"),
    "challenge_title": ("闖關任務 · {name}", "Quest · {name}"),
    "challenge_lead": (
        "設房間名稱與四位密碼，再選單人或多人。",
        "Set a name and 4-digit code, then pick solo or multiplayer.",
    ),
    "challenge_rooms_empty": ("還沒有房間", "No rooms yet"),
    "challenge_create": ("創建房間", "Create room"),
    "challenge_room_cap": (
        "未完成的房間最多 5 個",
        "At most 5 unfinished rooms",
    ),
    "challenge_room_name": ("房間名稱", "Room name"),
    "challenge_room_pin": ("四位密碼", "4-digit code"),
    "challenge_name_placeholder": ("例如主桌", "e.g. Head table"),
    "challenge_enter_room": ("進入房間", "Open room"),
    "challenge_delete_room": ("刪除房間", "Delete room"),
    "challenge_clear": ("清空挑戰者", "Clear players"),
    "challenge_qr_hint": (
        "掃碼後會帶入這組四碼",
        "Scan to fill this 4-digit code",
    ),
    "challenge_room_lead": (
        "請挑戰者掃 QR，房號會自動帶入。全部準備後開始。",
        "Players scan the QR; the room code fills in. Start when everyone is ready.",
    ),
    "challenge_join_lead": (
        "請確認桌上的四位密碼後進入",
        "Check the 4-digit code, then enter",
    ),
    "challenge_need_name": ("請填房間名稱", "Please enter a room name"),
    "challenge_bad_pin": ("請設 4 位數字密碼", "Use a 4-digit code"),
    "challenge_name_taken": ("房間名稱已存在", "That room name is already used"),
    "challenge_pin_taken": (
        "這個密碼已被其他進行中的房間使用",
        "That code is already used by a live room",
    ),
    "challenge_pin_wrong": (
        "密碼不對或房間不存在",
        "Wrong code or room not found",
    ),
    "challenge_cant_delete_live": (
        "進行中的房間不能刪除",
        "A room in progress cannot be deleted",
    ),
    "challenge_join_submit": ("進入", "Enter"),
    "challenge_play_mode": ("挑戰者", "Challenger"),
    "challenge_host_mode": ("關主", "Host"),
    "challenge_qr": ("QR code", "QR code"),
    "challenge_demo": ("單人模式", "Solo"),
    "challenge_adventure": ("多人模式", "Multiplayer"),
    "challenge_god": ("上帝視角", "God view"),
    "challenge_history": ("遊玩歷史", "Play history"),
    "challenge_history_empty": ("還沒有完賽紀錄", "No finished games yet"),
    "challenge_start": ("開始挑戰", "Start"),
    "challenge_live": ("進行中", "In progress"),
    "challenge_lobby": ("等待中 {n} 人 · 已準備 {k} 人", "Waiting {n} · {k} ready"),
    "challenge_join": ("加入挑戰", "Join"),
    "challenge_wait": ("請先按準備完成", "Tap Ready first"),
    "challenge_wait_host": ("已準備，等待主持人開始", "Ready. Waiting for the host to start"),
    "challenge_ready": ("準備完成", "Ready"),
    "challenge_edit": ("點擊照片及名稱\n可更換", "Tap photo or name\nto change"),
    "challenge_edit_hint": (
        "點擊照片及名稱可更換。準備完成後就不能改。",
        "Tap your photo or name to change. Locked after Ready.",
    ),
    "challenge_profile_locked": ("已準備完成，不能再改", "Already ready; profile is locked"),
    "challenge_ready_yes": ("已準備", "Ready"),
    "challenge_ready_no": ("尚未準備", "Not ready"),
    "challenge_need_ready": (
        "全部玩家都要先按準備完成才能開始",
        "Every player must tap Ready before the game can start",
    ),
    "challenge_closed": ("目前沒有開放的挑戰", "No challenge is open right now"),
    "challenge_remain": ("剩餘 {m}:{s}", "{m}:{s} left"),
    "challenge_score": ("分數 {n}", "Score {n}"),
    "challenge_pts": ("{n}分", "{n} pts"),
    "challenge_upload": ("上傳照片", "Upload photo"),
    "challenge_upload_btn": ("上傳", "Upload"),
    "challenge_no_target": ("待上傳", "Waiting for a photo"),
    "challenge_orig": ("原圖", "Target"),
    "challenge_user_shot": ("上傳", "Upload"),
    "challenge_host_btn": ("驗收", "Check"),
    "challenge_finish": ("完成", "Finish"),
    "challenge_uploaded": ("已上傳，正在審核…", "Uploaded. Checking…"),
    "challenge_judging": ("審核中…", "Checking…"),
    "challenge_passed": ("完成", "Done"),
    "challenge_failed": ("未通過", "Failed"),
    "challenge_pending": ("未完成", "Open"),
    "challenge_awaiting": ("待主持人驗收", "Waiting for host"),
    "challenge_empty_slot": ("無玩家", "No player"),
    "challenge_preview": ("預覽", "Preview"),
    "challenge_pass": ("通過", "Pass"),
    "challenge_reject": ("退回", "Reject"),
    "challenge_settle": ("結算", "Results"),
    "challenge_results": ("結算 · {name}", "Results · {name}"),
    "challenge_wipe": ("清除闖關任務", "Clear all quests"),
    "challenge_wiped": (
        "已清除「{name}」的挑戰紀錄",
        "Cleared challenge records for “{name}”",
    ),
    "challenge_bad_kind": ("不支援的挑戰類型", "Unknown challenge type"),
    "challenge_busy": ("已有進行中的挑戰", "A challenge is already in progress"),
    "challenge_not_open": ("挑戰尚未開放", "The challenge is not open"),
    "challenge_full": ("多人房間已滿（最多 4 人）", "Multiplayer is full (max 4 players)"),
    "challenge_demo_full": ("單人模式僅限一人", "Solo is one player only"),
    "challenge_need_refresh": (
        "先完成低難度任務，才能獲得刷新機會",
        "Finish a low task to earn a refresh",
    ),
    "challenge_refresh": ("刷新", "Refresh"),
    "challenge_refresh_left": ("刷新機會 {n}", "Refresh {n}"),
    "challenge_approve": ("認可", "Approve"),
    "challenge_done_count": ("完成 {n} 次", "Done {n}×"),
    "challenge_band_high": ("高難度", "Hard"),
    "challenge_band_mid": ("中難度", "Medium"),
    "challenge_band_low": ("低難度", "Easy"),
    "challenge_band_solo": ("任務", "Task"),
    "challenge_doing": ("進行中", "Active"),
    "challenge_already_started": ("挑戰已經開始", "The challenge has already started"),
    "challenge_need_player": ("至少需要一名玩家才能開始", "Need at least one player to start"),
    "challenge_not_running": ("挑戰尚未開始或已結束", "The challenge is not running"),
    "challenge_not_player": ("你不在這場挑戰裡", "You are not in this challenge"),
    "challenge_not_done": ("還有任務未通過，不能提前完成", "Finish every task before ending early"),
    "challenge_no_upload": ("這一題不需要上傳照片", "This task does not take a photo"),
    "challenge_no_host": ("這一題不是主持人驗收", "This task is not host-checked"),
    "challenge_bad_review": ("現在不能驗收這一題", "This task cannot be reviewed now"),
    "challenge_no_task": ("找不到這個任務", "Task not found"),
    "challenge_not_all_done": ("還有玩家尚未結束", "Some players are still playing"),
    "challenge_kind_demo": ("單人", "Solo"),
    "challenge_kind_adventure": ("多人", "Multi"),
}


def __getattr__(name):
    try:
        return pick(_STRINGS[name])
    except KeyError:
        raise AttributeError(name) from None
