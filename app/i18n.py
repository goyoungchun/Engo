"""Korean / English UI strings.

One flat table keyed by a short id, each entry a (한국어, English) pair.
`t("save")` returns the string for whatever language is active.

Deliberately not gettext/.ts files: there are exactly two languages and no
translator workflow, so a dict that can be read and edited in one place beats
a toolchain that needs compiling.
"""

from __future__ import annotations

LANGUAGES = {"ko": "한국어", "en": "English"}
DEFAULT = "ko"

_current = DEFAULT
_listeners: list = []

S: dict[str, tuple[str, str]] = {
    # -- app / general --------------------------------------------------
    "app_title": ("Engo — 영어 공부 정리", "Engo — English Study Notes"),
    "save": ("저장", "Save"),
    "save_shortcut": ("저장  (Ctrl+S)", "Save  (Ctrl+S)"),
    "revert": ("되돌리기", "Revert"),
    "delete": ("삭제", "Delete"),
    "add_new": ("＋ 새로 추가", "＋ Add new"),
    "cancel": ("취소", "Cancel"),
    "close": ("닫기", "Close"),
    "ok": ("확인", "OK"),
    "yes": ("예", "Yes"),
    "no": ("아니오", "No"),
    "tag": ("태그", "Tag"),
    "tags": ("태그", "Tags"),
    "all": ("전체", "All"),
    "search": ("검색", "Search"),
    "count_items": ("{n}건", "{n} items"),
    "unsaved": ("● 저장하지 않은 변경 사항이 있습니다",
                "● You have unsaved changes"),
    "saved": ("저장했습니다", "Saved"),
    "search_result": ("검색 결과", "search results"),
    "nothing_to_save": ("저장할 내용 없음", "Nothing to save"),
    "nothing_to_save_body": ("내용을 입력한 뒤 저장해 주세요.",
                             "Type something first, then save."),
    "pick_or_add": ("왼쪽에서 항목을 고르거나 ＋ 새로 추가를 누르세요",
                    "Pick an item on the left, or press ＋ Add new"),

    # -- tabs -----------------------------------------------------------
    "tab_expressions": ("1. 영어 표현", "1. Expressions"),
    "tab_reading": ("2. 원문 해석", "2. Translate"),
    "tab_sentences": ("3. 외우고 싶은 문장", "3. Sentences"),
    "tab_grammar": ("4. 문법", "4. Grammar"),
    "tab_data": ("5. 데이터", "5. Data"),

    # -- expressions ----------------------------------------------------
    "expr_title": ("영어 표현", "Expression"),
    "expr_edit": ("영어 표현 편집", "Edit expression"),
    "expr_new": ("새 영어 표현", "New expression"),
    "col_english": ("영어 표현", "Expression"),
    "col_korean": ("한글 뜻", "Meaning"),
    "col_studied_on": ("공부한 날", "Studied on"),
    "col_box": ("복습 단계", "Review level"),
    "f_english": ("영어 표현", "Expression"),
    "f_korean": ("한글 뜻", "Meaning"),
    "f_note": ("메모", "Note"),
    "f_source": ("출처", "Source"),
    "f_studied_on": ("공부한 날", "Studied on"),
    "ph_english": ("예: hit the ground running", "e.g. hit the ground running"),
    "ph_korean": ("예: 시작하자마자 순조롭게 잘 해내다",
                  "e.g. to start something quickly and successfully"),
    "ph_note": ("어디서 봤는지, 헷갈렸던 점, 뉘앙스 등",
                "Where you saw it, what confused you, nuance…"),
    "ph_source": ("예: 뉴스 기사 / 미드 제목 / 책", "e.g. news article / TV show / book"),
    "ph_tags": ("쉼표로 구분 (예: 비즈니스, 관용구)",
                "Comma separated (e.g. business, idiom)"),
    "ph_search": ("검색 (영어·한글·메모·태그)", "Search (text, meaning, note, tag)"),

    # -- sentences ------------------------------------------------------
    "sent_title": ("외우고 싶은 문장", "Sentence to memorise"),
    "sent_edit": ("외우고 싶은 문장 편집", "Edit sentence"),
    "sent_new": ("새 외우고 싶은 문장", "New sentence"),
    "col_source_text": ("원문", "Original"),
    "col_translation": ("번역", "Translation"),
    "col_registered": ("등록일", "Added"),
    "f_original": ("원문", "Original"),
    "f_translation": ("번역", "Translation"),
    "f_registered": ("등록일", "Added"),
    "ph_sent_en": ("외우고 싶은 영어 문장 그대로", "The English sentence, as it is"),
    "ph_sent_ko": ("내 번역 또는 참고 번역", "Your translation, or a reference one"),
    "ph_sent_note": ("구조 분석, 왜 외우고 싶은지 등",
                     "Structure, why you want to memorise it…"),
    "starred": ("⭐ 우선 암기 문장으로 표시", "⭐ Mark as priority"),

    # -- grammar --------------------------------------------------------
    "gram_title": ("문법 정리", "Grammar note"),
    "gram_edit": ("문법 정리 편집", "Edit grammar note"),
    "gram_new": ("새 문법 정리", "New grammar note"),
    "col_point": ("주요 표현", "Point"),
    "col_explanation": ("설명", "Explanation"),
    "col_written_on": ("정리한 날", "Written on"),
    "f_point": ("주요 표현", "Point"),
    "f_explanation": ("설명", "Explanation"),
    "f_examples": ("예문", "Examples"),
    "f_written_on": ("정리한 날", "Written on"),
    "ph_point": ("예: 가정법 과거완료 (If + had p.p.)",
                 "e.g. Third conditional (If + had p.p.)"),
    "ph_explanation": ("규칙, 언제 쓰는지, 헷갈리는 지점",
                       "The rule, when to use it, what trips you up"),
    "ph_examples": ("한 줄에 하나씩 적어두면 보기 편합니다", "One per line reads best"),
    "ph_gram_tags": ("쉼표로 구분 (예: 시제, 관계사)",
                     "Comma separated (e.g. tense, relative clause)"),

    # -- delete confirm -------------------------------------------------
    "delete_confirm": ("삭제 확인", "Confirm delete"),
    "delete_body": (
        "{n}건을 삭제할까요?\n\n휴지통처럼 표시만 지워지고, 다른 기기와 병합할 때 "
        "그 기기에서도 삭제되도록 기록이 남습니다.",
        "Delete {n} item(s)?\n\nThey are hidden rather than erased, and the "
        "deletion is recorded so it carries over when you merge with another "
        "device."),

    # -- reading tab ----------------------------------------------------
    "reading_pick": ("지문을 고르거나 새로 추가하세요", "Pick a passage, or add one"),
    "passage_search": ("지문 검색", "Search passages"),
    "new_passage": ("＋ 새 지문", "＋ New passage"),
    "new_passage_title": ("새 지문 추가", "Add a passage"),
    "resplit": ("원문 다시 나누기", "Re-split the text"),
    "resplit_tip": ("원문을 고쳐서 다시 문장 단위로 나눕니다. "
                    "내용이 바뀌지 않은 문장의 해석은 그대로 유지됩니다.",
                    "Edit the text and split it into sentences again. "
                    "Translations of unchanged sentences are kept."),
    "send_to_sentences": ("선택 문장 → 외우고 싶은 문장", "Selected → Sentences"),
    "send_tip": ("고른 행의 원문과 내 해석을 그대로 3번 탭에 추가합니다",
                 "Copies the chosen rows into the Sentences tab"),
    "col_no": ("#", "#"),
    "col_star": ("★", "★"),
    "col_source_en": ("영어 원문", "English"),
    "col_my_translation": ("내 해석", "My translation"),
    "col_feedback": ("피드백 메모", "Feedback note"),
    "reading_hint": ("해석·메모 칸을 더블클릭하면 바로 입력됩니다. 입력한 내용은 자동 저장됩니다.",
                     "Double-click a translation or note cell to type. Saved automatically."),
    "progress_done": ("{done} / {total} 문장 해석함", "{done} / {total} sentences done"),
    "progress_short": ("{done}/{total} 문장 해석함", "{done}/{total} done"),
    # passage length, by sentence count -- shown so the reader can pick a
    # short one for a quick session or a long one to dig in.
    "len_short": ("짧음", "Short"),
    "len_medium": ("중간", "Medium"),
    "len_long": ("김", "Long"),
    "f_title": ("제목", "Title"),
    "ph_passage_title": ("예: BBC 기사 - Climate report 2026",
                         "e.g. BBC article - Climate report 2026"),
    "f_tags_optional": ("태그 (쉼표로 구분, 선택)", "Tags (comma separated, optional)"),
    "paste_here": ("영어 원문 — 붙여넣으면 문장마다 한 행으로 나뉩니다",
                   "English text — pasted text is split into one row per sentence"),
    "ph_paste": ("Paste the English text here…", "Paste the English text here…"),
    "split_button": ("문장으로 나누기", "Split into sentences"),
    "no_text": ("원문 없음", "No text"),
    "no_text_body": ("영어 원문을 붙여넣어 주세요.", "Please paste some English text."),
    "delete_passage": ("지문 삭제", "Delete passage"),
    "delete_passage_body": ("'{title}' 지문과 해석을 모두 삭제할까요?",
                            "Delete '{title}' and all its translations?"),
    "no_selection": ("선택 없음", "Nothing selected"),
    "no_selection_body": ("보낼 문장의 행을 먼저 고르세요.",
                          "Select the rows you want to send first."),
    "added": ("추가 완료", "Added"),
    "added_body": ("{n}개 문장을 '외우고 싶은 문장'에 추가했습니다.",
                   "Added {n} sentence(s) to Sentences."),
    "untitled": ("제목 없음", "Untitled"),

    # -- news import ----------------------------------------------------
    "fetch_news": ("＋ 최신 기사 가져오기", "＋ Fetch recent articles"),
    "fetch_news_title": ("최신 기사 가져오기", "Fetch recent articles"),
    "news_intro": ("공부할 영어 지문을 골라온 매체에서 최신순으로 몇 편 가져옵니다. "
                   "중복 없이 무작위로 섞어서 담습니다.",
                   "Brings in a few recent articles from the chosen sources as "
                   "passages to translate — shuffled, with no repeats."),
    "news_sources": ("매체", "Sources"),
    "news_themes": ("주제", "Themes"),
    "news_count": ("가져올 개수", "How many"),
    "news_fetch_btn": ("가져오기", "Fetch"),
    "news_fetching": ("기사를 가져오는 중…", "Fetching articles…"),
    "news_offline": ("인터넷에 연결할 수 없어 기사를 가져오지 못했습니다.",
                     "Could not reach the internet, so no articles were fetched."),
    "news_empty": ("새로 가져올 기사가 없습니다. 잠시 뒤 다시 시도하거나 다른 주제를 골라보세요.",
                   "No new articles right now. Try again later or pick another theme."),
    "news_need_pick": ("매체와 주제를 하나 이상 골라주세요.",
                       "Pick at least one source and one theme."),
    "news_done": ("기사 {n}편을 지문으로 담았습니다.", "Added {n} article(s) as passages."),
    "news_source_label": ("출처: {name}", "Source: {name}"),
    "news_open_original": ("원문 보기 ↗", "Read the original ↗"),

    # licences shown next to each source
    "lic_cc": ("크리에이티브 커먼즈", "Creative Commons"),
    "lic_public": ("공영방송", "Public broadcaster"),
    "lic_publicdomain": ("퍼블릭 도메인", "Public domain"),

    # themes
    "theme_world": ("세계", "World"),
    "theme_business": ("경제", "Business"),
    "theme_technology": ("기술", "Technology"),
    "theme_science": ("과학", "Science"),
    "theme_health": ("건강", "Health"),

    # the disclaimer -- shown before the first fetch, agreed to once
    "news_disclaimer_title": ("가져오기 전에 — 잠깐 확인해주세요",
                              "Before you fetch — please read"),
    "news_disclaimer_body": (
        "이 기능은 오직 개인 영어 공부를 위한 것입니다.\n\n"
        "· 가져온 기사는 저작권이 있는 글입니다. 개인 학습 용도로만 쓰고, "
        "복제·재배포·공유·상업적 이용을 하지 마세요.\n"
        "· 각 기사의 출처와 원문 링크가 함께 저장됩니다. 원문은 링크에서 확인하세요.\n"
        "· 이 기능을 사용해 발생하는 저작권 등 법적 문제에 대한 책임은 "
        "전적으로 사용자 본인에게 있습니다.\n\n"
        "재사용이 허용된 매체(크리에이티브 커먼즈·공공·퍼블릭 도메인)만 담았지만, "
        "이용 방식에 대한 책임은 사용자에게 있습니다.",
        "This feature is only for your own personal English study.\n\n"
        "· The articles are copyrighted. Use them for personal study only — do "
        "not copy, redistribute, share, or use them commercially.\n"
        "· Each article's source and a link to the original are saved with it. "
        "Read the original at the link.\n"
        "· You alone are responsible for any legal issues, copyright included, "
        "arising from your use of this feature.\n\n"
        "Only sources that permit reuse (Creative Commons, public, public "
        "domain) are included, but how you use them is your responsibility."),
    "news_agree": ("이해했고, 개인 학습 목적으로만 사용하겠습니다",
                   "I understand and will use this for personal study only"),
    "news_disclaimer_ok": ("동의하고 계속", "Agree and continue"),
    "news_disclaimer_reminder": ("개인 학습 전용 · 저작권 준수 · 책임은 사용자 본인",
                                 "Personal study only · respect copyright · your responsibility"),

    # -- sticky notes ---------------------------------------------------
    "sticky": ("복습 메모지", "Review note"),
    "sticky_new": ("📌 복습 메모지 (오늘 공부한 것)", "📌 Review note (today)"),
    "sticky_weak": ("📌 헷갈리는 표현만", "📌 Only the shaky ones"),
    "sticky_sentences": ("📌 외우고 싶은 문장", "📌 Sentences to memorise"),
    "sticky_settings": ("메모지 설정", "Note settings"),
    "reveal": ("👆 눌러서 뜻 보기", "👆 Tap to reveal"),
    "empty_meaning": ("(뜻이 비어 있습니다)", "(no meaning yet)"),
    "know": ("알아요", "I know it"),
    "unsure": ("헷갈려요", "Not sure"),
    "tip_reveal": ("뜻 전체 보이기 / 가리기", "Show / hide all meanings"),
    "tip_refresh": ("다시 불러오기", "Reload"),
    "tip_settings": ("설정", "Settings"),
    "tip_close": ("닫기", "Close"),
    "scope_today": ("오늘 공부한 것", "Today's study"),
    "scope_weak": ("헷갈리는 것", "Shaky ones"),
    "scope_weak_long": ("헷갈리는 것만 (복습 단계 낮은 순)", "Only shaky ones (lowest level first)"),
    "scope_all": ("전체", "Everything"),
    "what_to_review": ("무엇을 복습할까요", "What to review"),
    "scope": ("범위", "Scope"),
    "colour": ("색상", "Colour"),
    "hide_meaning": ("한글 뜻을 가린 채로 열기", "Open with meanings hidden"),
    "always_on_top": ("항상 다른 창 위에 두기", "Keep above other windows"),
    "always_on_top_short": ("항상 위에 두기", "Always on top"),
    "opacity": ("투명도", "Opacity"),
    "batch_status": ("{shown}건 표시 · 전체 {total}건 · ⟳ 로 다음 묶음",
                     "{shown} shown · {total} total · ⟳ for the next batch"),
    "remaining": ("{n}건 남음", "{n} left"),
    "sticky_empty_today": ("오늘 정리한 표현이 아직 없습니다.\n메인 창에서 표현을 추가해 보세요.",
                           "Nothing studied today yet.\nAdd an expression in the main window."),
    "sticky_empty_other": ("이 범위에 복습할 항목이 없습니다.\n⚙ 설정에서 범위를 바꿔보세요.",
                           "Nothing to review in this scope.\nTry another scope in ⚙ settings."),
    "kind_expressions": ("영어 표현", "Expressions"),
    "kind_sentences": ("외우고 싶은 문장", "Sentences"),
    "close_this_note": ("이 메모지 닫기", "Close this note"),
    "settings_dots": ("설정…", "Settings…"),
    "notes_restored": ("복습 메모지 {n}개를 다시 띄웠습니다.", "Reopened {n} review note(s)."),

    # -- review levels --------------------------------------------------
    "box_new": ("새 항목", "New"),
    "box_1": ("1단계", "Level 1"),
    "box_2": ("2단계", "Level 2"),
    "box_3": ("3단계", "Level 3"),
    "box_4": ("4단계", "Level 4"),
    "box_done": ("완료", "Done"),

    # -- menus ----------------------------------------------------------
    "menu_study": ("학습(&S)", "&Study"),
    "menu_view": ("보기(&V)", "&View"),
    "menu_data": ("데이터(&D)", "&Data"),
    "menu_help": ("도움말(&H)", "&Help"),
    "menu_new_note": ("복습 메모지 새로 띄우기", "New review note"),
    "menu_weak_note": ("헷갈리는 표현만 메모지로", "Note with only the shaky ones"),
    "menu_sentence_note": ("외우고 싶은 문장 메모지", "Note with sentences"),
    "menu_save_current": ("현재 항목 저장", "Save current item"),
    "menu_hide_tray": ("트레이로 숨기기", "Hide to tray"),
    "menu_theme": ("색 테마", "Colour theme"),
    "menu_voice": ("읽어주기 음성", "Reading voice"),
    "voice_off": ("읽어주기 끄기", "Turn reading off"),
    "tts_loading": ("🔊 음성 바꾸는 중… ({voice})", "🔊 Changing voice… ({voice})"),
    "tts_speaking": ("🔊 읽는 중… ({voice})", "🔊 Speaking… ({voice})"),
    "tts_error": ("🔊 음성을 불러오지 못했습니다", "🔊 Could not load the voice"),

    # -- voice download -------------------------------------------------
    "voices_title": ("읽어주기 음성 내려받기", "Download speech voices"),
    "voices_ask": ("영어를 소리로 들으려면 음성 파일이 필요합니다. 지금 받을까요? (약 {size} MB)",
                   "Hearing the English out loud needs voice files. "
                   "Download them now? (about {size} MB)"),
    "voices_ask_detail": (
        "한 번만 받으면 됩니다. 받은 뒤에는 인터넷 없이 동작합니다.\n"
        "받지 않아도 나머지 기능은 모두 그대로 쓸 수 있고, 🔊 버튼만 숨겨집니다.",
        "A one-time download; after that it works with no internet.\n"
        "Everything else works without it — only the 🔊 buttons are hidden."),
    "voices_download": ("지금 받기", "Download now"),
    "voices_later": ("나중에", "Later"),
    "voices_never": ("묻지 않기", "Don't ask again"),
    "voices_downloading": ("음성 파일을 내려받는 중입니다…", "Downloading voice files…"),
    "voices_cancelling": ("취소하는 중…", "Cancelling…"),
    "voices_failed": ("내려받지 못했습니다:\n{err}", "Download failed:\n{err}"),
    "voices_box": ("읽어주기 음성", "Speech voices"),
    "voices_ready": ("음성 {n}개 준비됨", "{n} voice(s) ready"),
    "voices_missing": ("음성 파일이 없어 읽어주기를 쓸 수 없습니다",
                       "No voice files, so reading aloud is unavailable"),
    "voices_get": ("음성 내려받기", "Get voices"),
    "voices_get_extra": ("나머지 음성도 받기", "Get the other voices"),
    "voices_settings": ("음성 설정", "Voice settings"),

    # -- voice slots ----------------------------------------------------
    "slots_title": ("음성 4칸 설정", "Voice slots"),
    "slots_intro": ("칸마다 원하는 음성 파일과 이름을 정할 수 있습니다. "
                    "여기서 정한 이름이 읽어주기 메뉴에 그대로 나옵니다.",
                    "Point each slot at whichever voice you like and name it "
                    "yourself. These names are what the reading menu shows."),
    "slots_col_name": ("이름", "Name"),
    "slots_col_model": ("음성 파일", "Voice file"),
    "slots_col_state": ("상태", "State"),
    "default_mark": ("(기본값)", "(default)"),
    "slots_ready": ("받아둠", "ready"),
    "slots_not_ready": ("없음", "not downloaded"),
    "slots_get": ("받기", "Get"),
    "slots_reset": ("기본값으로", "Restore defaults"),
    "slots_need_name": ("이름이 비어 있는 칸이 있습니다.", "A slot has no name."),
    "slots_saved_missing": ("저장했습니다. 아직 받지 않은 음성이 있습니다: {names}",
                            "Saved. These are not downloaded yet: {names}"),
    "speak_tip": ("영어를 소리로 듣기  (Ctrl+P)", "Hear the English  (Ctrl+P)"),
    "menu_speak": ("현재 항목 읽어주기", "Read the current item"),
    "menu_language": ("언어 / Language", "Language / 언어"),
    "menu_open_data": ("데이터 관리 열기", "Open data manager"),
    "menu_open_folder": ("저장 폴더 열기", "Open data folder"),
    "menu_about": ("이 프로그램에 대해", "About this program"),
    "tray_open": ("메인 창 열기", "Open main window"),
    "tray_refresh_notes": ("열린 메모지 모두 새로고침", "Refresh all open notes"),
    "tray_close_notes": ("열린 메모지 모두 닫기", "Close all open notes"),
    "tray_autostart": ("윈도우 시작할 때 자동 실행", "Start with Windows"),
    "tray_quit": ("종료", "Quit"),
    "autostart_failed": ("자동 실행 설정 실패", "Could not set autostart"),
    "autostart_failed_body": (
        "레지스트리에 접근하지 못했습니다.\n시작 프로그램 폴더에 바로가기를 직접 넣어도 됩니다.",
        "Could not write to the registry.\nYou can add a shortcut to the "
        "Startup folder instead."),

    # -- status bar -----------------------------------------------------
    "status": ("표현 {expr}   ·   문장 {sent}   ·   문법 {gram}   ·   지문 {pass}"
               "      |      오늘 {today}건   ·   복습 필요 {weak}건   ·   메모지 {notes}개",
               "Expressions {expr}   ·   Sentences {sent}   ·   Grammar {gram}   ·   "
               "Passages {pass}      |      Today {today}   ·   To review {weak}   ·   "
               "Notes {notes}"),
    "about_body": (
        "<b>Engo</b><br>영어 표현·문장·문법을 직접 정리하고, "
        "복습 메모지로 다시 보는 프로그램입니다.<br><br>"
        "저장 위치: {path}<br>기기 이름: {device} ({id})<br><br>"
        "데이터는 이 컴퓨터에만 저장됩니다. 다른 기기와는 "
        "<b>데이터</b> 탭에서 파일로 주고받아 합칠 수 있습니다.",
        "<b>Engo</b><br>Write up the expressions, sentences and grammar "
        "you study, then review them on sticky notes.<br><br>"
        "Stored at: {path}<br>Device: {device} ({id})<br><br>"
        "Your data stays on this computer. To move it between machines, use "
        "the <b>Data</b> tab to export and merge a file."),

    # -- data tab -------------------------------------------------------
    "this_device": ("이 기기", "This device"),
    "device_name": ("기기 이름", "Device name"),
    "device_info": ("기기 ID {id}   ·   저장 위치 {path}   ·   {size} KB",
                    "Device ID {id}   ·   Stored at {path}   ·   {size} KB"),
    "export_box": ("내보내기 — 다른 기기로 옮길 파일 만들기",
                   "Export — make a file to carry to another device"),
    "export_full": ("전체 내보내기", "Export everything"),
    "export_incremental": ("마지막 내보내기 이후 변경분만", "Only changes since last export"),
    "export_button": ("파일로 내보내기", "Export to file"),
    "export_hint": ("마지막 내보내기: {when}   ·   변경분만 내보내면 파일이 작아지고, "
                    "합쳤을 때 결과는 전체 내보내기와 같습니다.",
                    "Last export: {when}   ·   Exporting only changes makes a "
                    "smaller file and merges to the same result."),
    "import_box": ("가져오기 — 다른 기기에서 만든 파일 합치기",
                   "Import — merge a file from another device"),
    "ph_import": ("합칠 .seb 파일을 고르세요", "Choose a .seb file to merge"),
    "choose_file": ("파일 선택…", "Choose file…"),
    "preview_merge": ("병합 미리보기", "Preview merge"),
    "do_merge": ("합치기", "Merge"),
    "backup_first": ("합치기 전에 지금 상태를 자동 백업", "Back up before merging"),
    "merge_rule": (
        "같은 항목이 양쪽에 있으면 <b>더 나중에 수정한 쪽</b>이 남습니다. "
        "한쪽에만 있는 항목은 그대로 추가되고, 한쪽에서 지운 항목은 삭제가 함께 반영됩니다. "
        "같은 파일을 두 번 합쳐도 결과는 같습니다.",
        "When an item exists on both sides, <b>the one edited more recently</b> "
        "wins. Items on only one side are added, and deletions carry over. "
        "Merging the same file twice changes nothing."),
    "other_box": ("CSV 주고받기 · 백업 · 정리", "CSV · Backup · Clean up"),

    # -- update ---------------------------------------------------------
    "update_box": ("프로그램 업데이트", "Program update"),
    "update_check": ("업데이트 확인", "Check for updates"),
    "update_apply": ("업데이트 설치", "Install update"),
    "update_checking": ("확인 중…", "Checking…"),
    "update_latest": ("최신 버전입니다  (v{current})", "Up to date  (v{current})"),
    "update_available": ("새 버전 v{latest} 이 나왔습니다  (현재 v{current})",
                         "Version {latest} is available  (you have {current})"),
    "update_offline": ("업데이트를 확인하지 못했습니다 — 인터넷 연결을 확인하세요",
                       "Could not check for updates — check your connection"),
    "update_error": ("업데이트 확인 중 문제가 생겼습니다", "Something went wrong while checking"),
    "update_dirty": ("이 폴더의 파일을 직접 고친 흔적이 있어 업데이트하지 않았습니다.\n\n"
                     "고친 내용이 지워지지 않도록 멈춘 것입니다.",
                     "Files in this folder have been edited, so the update was "
                     "not applied.\n\nStopping here keeps your changes safe."),
    "update_downloading": ("새 버전을 받는 중입니다…", "Downloading the new version…"),
    "update_done": ("업데이트 완료", "Update finished"),
    "update_done_body": ("v{latest} 으로 업데이트했습니다.\n\n"
                         "프로그램을 껐다 켜면 적용됩니다.",
                         "Updated to v{latest}.\n\n"
                         "Restart the program to start using it."),
    "update_whats_new": ("바뀐 점", "What's new"),
    "update_notes_title": ("업데이트", "Update"),
    "update_notes_versions": ("v{current}  →  v{latest}",
                              "v{current}  →  v{latest}"),
    "update_notes_hint": (
        "설치하면 프로그램 파일이 새 버전으로 바뀝니다. 학습 데이터와 "
        "내려받은 음성은 그대로 유지되고, 설치 후 프로그램을 껐다 켜면 "
        "적용됩니다.",
        "Installing replaces the program files. Your study data and "
        "downloaded voices are kept, and the update takes effect the next "
        "time you start the program."),
    "update_no_notes": ("이번 릴리스에 적힌 설명이 없습니다.",
                        "This release has no notes."),
    "update_now": ("지금 업데이트", "Update now"),
    "update_later": ("나중에", "Not now"),
    "update_failed": ("업데이트 실패", "Update failed"),
    "log_update": ("업데이트 — {msg}", "Update — {msg}"),
    "open_github": ("GitHub에서 보기", "View on GitHub"),
    "tab_data_update": ("5. 데이터 ●", "5. Data ●"),
    "export_csv": ("CSV로 내보내기", "Export CSV"),
    "import_csv": ("CSV 가져오기", "Import CSV"),
    "import_csv_tip": ("엑셀 등에서 정리한 표를 새 항목으로 추가합니다 (병합이 아니라 추가)",
                       "Adds rows from a spreadsheet as new items (adds, does not merge)"),
    "backup_now": ("지금 백업", "Back up now"),
    "purge": ("정리", "Clean up"),
    "purge_tip": ("180일보다 오래된 삭제 기록을 완전히 지우고 파일 크기를 줄입니다",
                  "Erase deletion records older than 180 days and shrink the file"),
    "log_placeholder": ("작업 결과가 여기에 표시됩니다.", "Results will appear here."),

    # -- removing the program ------------------------------------------
    "uninstall_box": ("프로그램 삭제", "Remove Engo"),
    "uninstall_desc": (
        "이 컴퓨터에서 Engo가 만든 학습 데이터와, 설치할 때 새로 내려받은 "
        "구성 요소를 지웁니다. 원래 이 컴퓨터에 있던 것은 건드리지 않습니다.",
        "Deletes the study data Engo created and the components setup "
        "downloaded. Anything that was already on this computer is left alone."),
    "uninstall_btn": ("모든 데이터 및 프로그램 삭제", "Delete all data and remove Engo"),
    "uninstall_confirm_title": ("정말 삭제할까요?", "Delete everything?"),
    "uninstall_confirm_body": (
        "이 컴퓨터에서 Engo의 학습 데이터를 모두 지웁니다.\n\n{items}\n"
        "    위치: {path}\n\n"
        "지우면 되돌릴 수 없습니다. 남겨두고 싶다면 먼저 '내보내기'로 "
        "저장하세요.\n\n정말 삭제할까요?",
        "This deletes all of Engo's study data on this computer.\n\n{items}\n"
        "    Location: {path}\n\n"
        "It cannot be undone. If you want to keep it, export a file "
        "first.\n\nDelete it anyway?"),
    "uninstall_parts_title": ("내려받은 구성 요소도 지울까요?",
                              "Remove the downloaded components too?"),
    "uninstall_parts_body": (
        "설치할 때 이 컴퓨터에 없어서 새로 내려받은 것들입니다.\n\n{items}\n"
        "{kept}\n남겨두면 나중에 다시 설치할 때 내려받지 않아도 됩니다.\n\n"
        "함께 지울까요?",
        "These were downloaded during setup because they were missing.\n\n"
        "{items}\n{kept}\nKeeping them saves the download if you reinstall "
        "later.\n\nRemove them as well?"),
    "uninstall_kept": ("\n원래 있던 것이라 지우지 않습니다:\n{items}\n",
                       "\nAlready on this computer, so left in place:\n{items}\n"),
    "uninstall_kept_venv": ("직접 만든 가상환경 (.venv)",
                            "Your own virtual environment (.venv)"),
    "uninstall_foreign": (
        "\nEngo가 만든 것이 아니라서 남겨 둔 파일:\n{items}\n",
        "\nLeft in place because Engo did not create them:\n{items}\n"),
    "uninstall_done_title": ("삭제했습니다", "Removed"),
    "uninstall_done_body": ("지운 항목:\n{items}\n", "Deleted:\n{items}\n"),
    "uninstall_deferred": (
        "\n가상환경(.venv)은 지금 실행 중이라, 프로그램이 완전히 닫힌 뒤에 "
        "자동으로 지워집니다.\n",
        "\nThe virtual environment is in use right now, so it is removed "
        "automatically once the program has closed.\n"),
    "uninstall_folder": (
        "\n마지막으로 프로그램 폴더는 직접 지워 주세요:\n{path}\n\n"
        "'확인'을 누르면 Engo가 종료됩니다.",
        "\nFinally, delete the program folder yourself:\n{path}\n\n"
        "Engo closes when you press OK."),
    "uninstall_open_folder": ("폴더 열기", "Open folder"),
    "uninstall_failed": ("\n지우지 못한 항목:\n{items}\n",
                         "\nCould not delete:\n{items}\n"),
    "uninstall_nothing": ("지울 데이터가 없습니다.", "There is no data to delete."),
    "export_dialog": ("학습 데이터 내보내기", "Export study data"),
    "export_failed": ("내보내기 실패", "Export failed"),
    "export_done": ("내보내기 완료", "Export finished"),
    "export_done_body": ("{n}행을 저장했습니다.\n\n{path}\n\n"
                         "이 파일을 다른 기기로 옮긴 뒤 '가져오기'에서 합치면 됩니다.",
                         "Saved {n} rows.\n\n{path}\n\n"
                         "Copy it to the other device and merge it there."),
    "import_dialog": ("가져올 파일 선택", "Choose a file to import"),
    "unreadable": ("읽을 수 없는 파일", "Cannot read this file"),
    "not_engo_file": ("이 파일은 Engo 내보내기 파일이 아닙니다.",
                      "This is not an Engo export file."),
    "file_from_future": ("더 새로운 버전에서 만든 파일입니다. 프로그램을 먼저 업데이트하세요.",
                         "This file was made by a newer version. Update the program first."),
    "file_too_large": ("파일이 비정상적으로 큽니다. Engo 내보내기 파일이 맞는지 확인하세요.",
                       "This file is abnormally large. Check that it is really an Engo export."),
    "unexpected_error": ("예상하지 못한 문제가 생겨 마지막 동작이 완료되지 않았습니다.\n\n"
                         "자세한 내용이 기록되었습니다:\n{path}",
                         "Something unexpected went wrong and the last action "
                         "did not finish.\n\nDetails were written to:\n{path}"),
    "import_failed": ("가져오기 실패", "Import failed"),
    "merge_preview": ("병합 미리보기", "Merge preview"),
    "merge_done": ("합치기 완료", "Merge finished"),
    "preview_note": ("\n\n※ 미리보기입니다. 실제로 반영되지 않았습니다.",
                     "\n\nThis was a preview. Nothing was changed."),
    "backup_failed": ("백업 실패", "Backup failed"),
    "backup_failed_body": ("백업에 실패했습니다:\n{err}\n\n그래도 합칠까요?",
                           "Backup failed:\n{err}\n\nMerge anyway?"),
    "backup_done": ("백업 완료", "Backup finished"),
    "done": ("완료", "Done"),
    "csv_done": ("{n}행을 CSV로 저장했습니다.", "Saved {n} rows to CSV."),
    "csv_import_confirm": ("첫 줄이 열 이름이어야 합니다:\n{fields}\n\n"
                           "모든 행이 새 항목으로 추가됩니다 (병합 아님). 계속할까요?",
                           "The first row must be column names:\n{fields}\n\n"
                           "Every row is added as a new item (not merged). Continue?"),
    "csv_added": ("{n}행을 추가했습니다.", "Added {n} rows."),
    "purge_confirm": ("180일보다 오래된 삭제 기록을 완전히 지웁니다.\n\n"
                      "그동안 한 번도 합치지 않은 기기가 있다면, 그 기기와 합칠 때 "
                      "지웠던 항목이 되살아날 수 있습니다. 계속할까요?",
                      "This erases deletion records older than 180 days.\n\n"
                      "If a device has not merged since then, items you deleted "
                      "may come back when you merge with it. Continue?"),
    "log_export": ("내보내기 완료 — {n}행, {size} KB → {path}",
                   "Exported — {n} rows, {size} KB → {path}"),
    "log_file_ok": ("파일 확인 — {device} 에서 {when} 에 만든 {kind} 파일, {n}행",
                    "File read — {kind} export from {device}, made {when}, {n} rows"),
    "kind_full": ("전체", "full"),
    "kind_partial": ("변경분", "incremental"),
    "log_merge": ("{title} — 추가 {added} / 갱신 {updated} / 유지 {skipped}",
                  "{title} — added {added} / updated {updated} / kept {skipped}"),
    "log_backup": ("자동 백업 — {path}", "Auto backup — {path}"),
    "log_backup_done": ("백업 완료 — {path}", "Backup finished — {path}"),
    "log_csv_out": ("CSV 내보내기 — {n}행 → {path}", "CSV export — {n} rows → {path}"),
    "log_csv_in": ("CSV 가져오기 — {n}행 추가", "CSV import — {n} rows added"),
    "log_purge": ("정리 완료 — 삭제 기록 {n}건 제거",
                  "Clean up finished — {n} deletion records removed"),
    "none": ("없음", "none"),
    "filter_export": ("Engo 학습 데이터 (*.seb);;JSON 파일 (*.json);;모든 파일 (*.*)",
                      "Engo data (*.seb);;JSON file (*.json);;All files (*.*)"),
    "filter_csv": ("CSV 파일 (*.csv)", "CSV file (*.csv)"),

    # -- merge report ---------------------------------------------------
    "rp_from": ("보낸 기기: {device}", "From device: {device}"),
    "rp_added": ("새로 추가: {n}건", "Added: {n}"),
    "rp_updated": ("덮어쓴 항목: {n}건", "Overwritten: {n}"),
    "rp_skipped": ("그대로 둔 항목: {n}건 (내 쪽이 더 최신)",
                   "Kept as-is: {n} (mine were newer)"),
    "rp_deleted": ("삭제 반영: {n}건", "Deletions applied: {n}"),
    "rp_unknown": ("알 수 없음", "unknown"),
}


_qt_translator = None


def install_qt_translator(app) -> None:
    """Localise Qt's own stock buttons (Yes / No / OK / Cancel …).

    Every string WE write goes through t(), but QMessageBox and QFileDialog
    render their standard buttons from Qt's catalogue -- without this a
    Korean user confirms deletions on an English "Yes/No". PySide6 ships the
    .qm files, so this is a load, not a translation effort.
    """
    global _qt_translator
    from PySide6.QtCore import QLibraryInfo, QTranslator

    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if _current == "en":
        return          # Qt's built-in strings are already English
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    if translator.load(f"qtbase_{_current}", path):
        app.installTranslator(translator)
        _qt_translator = translator


def language() -> str:
    return _current


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES or code == _current:
        return
    _current = code
    for callback in list(_listeners):
        callback(code)


def on_change(callback) -> None:
    _listeners.append(callback)


def t(key: str, **kwargs) -> str:
    pair = S.get(key)
    if pair is None:
        return key                      # visible, so a missing key is obvious
    text = pair[1] if _current == "en" else pair[0]
    return text.format(**kwargs) if kwargs else text


def box_label(level: int) -> str:
    return t(("box_new", "box_1", "box_2", "box_3", "box_4",
              "box_done")[max(0, min(int(level or 0), 5))])


