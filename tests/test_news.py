"""Fetching articles: parsing, de-duplication, cleaning, and the disclaimer.

The parsing and merge logic run against canned feed bytes so the test is
deterministic; one live fetch at the end confirms the real feeds still answer
in the shape the parser expects. The disclaimer gate and passage creation run
through the real dialogs.

Run:  .venv\\Scripts\\python.exe tests\\test_news.py
"""

from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_ROOT = tempfile.mkdtemp(prefix="engo_news_")
os.environ["ENGO_HOME"] = _ROOT
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication, QDialog     # noqa: E402

app = QApplication.instance() or QApplication([])

from app import db, news, repo, theme                   # noqa: E402

db.connect()
theme.apply(app, "violet")

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


RSS = """<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
 <item><title>First &amp; foremost</title><link>https://ex.com/a</link>
   <guid>g-a</guid>
   <description>&lt;p&gt;A short summary that is definitely long enough to keep.&lt;/p&gt;</description></item>
 <item><title>Second story</title><link>https://ex.com/b</link>
   <guid>g-b</guid>
   <content:encoded>&lt;figure&gt;&lt;figcaption&gt;A photo. Getty&lt;/figcaption&gt;&lt;/figure&gt;&lt;p&gt;The real body starts here and runs on for a good while so it survives the length filter.&lt;/p&gt;</content:encoded></item>
 <item><title>Too short</title><link>https://ex.com/c</link><guid>g-c</guid>
   <description>tiny</description></item>
</channel></rss>"""


def with_feeds(payload_by_url):
    original = news._fetch_feed
    news._fetch_feed = lambda url: payload_by_url.get(url, b"").encode("utf-8") \
        if isinstance(payload_by_url.get(url, b""), str) else payload_by_url.get(url, b"")
    return original


def main() -> int:
    print("[정리: HTML·엔티티·이미지 캡션]")
    check("태그가 제거된다", news.clean("<p>hi <b>there</b></p>") == "hi there")
    check("엔티티가 풀린다", news.clean("A &amp; B &mdash; C") == "A & B — C")
    check("저자 공개(fine-print)가 제거된다",
          "does not work for" not in news.clean(
              "<p>Body here now.</p><p class=\"fine-print\"><em>Jane Doe does "
              "not work for, consult, own shares in any company.</em></p>"),
          news.clean("<p>Body.</p><p class='fine-print'>Jane Doe does not "
                     "work for anyone.</p>"))
    check("이미지 캡션(figure)이 통째로 제거된다",
          "Getty" not in news.clean(
              "<figure><figcaption>x Getty</figcaption></figure><p>body</p>"),
          news.clean("<figure><figcaption>x Getty</figcaption></figure><p>body</p>"))
    check("깨진 태그 잔해(NPR '/>)가 제거된다",
          "/>" not in news.clean("emotional support.'/><p>next</p>"),
          news.clean("emotional support.'/><p>next</p>"))

    print("\n[소제목 표시]")
    heads = [ln for ln in news.clean(
        "<p>Body one here now.</p><h2>A Section Title</h2>"
        "<p>Body two here now.</p>").split("\n") if news.is_heading(ln)]
    check("h2 소제목이 '## ' 줄로 표시된다", heads == ["## A Section Title"], str(heads))
    check("heading_text 가 '## '를 뗀다", news.heading_text("## Title") == "Title")
    check("일반 문장은 소제목이 아니다", not news.is_heading("Just a sentence."))
    split = repo.split_sentences(news.clean(
        "<p>First. Second.</p><h3>Heading Here</h3><p>Third one.</p>"))
    check("소제목이 한 줄로 분리된다", "## Heading Here" in split, str(split))
    check("진짜 부등호는 유지된다",
          news.clean("5 > 3 and a < b") == "5 > 3 and a < b")
    # Longer than the sanity ceiling, so the cap actually engages.
    long = "A sentence. " * (news.MAX_BODY // 8)
    check("상한을 넘는 본문만 잘린다", len(news._cap(long)) <= news.MAX_BODY)
    check("잘릴 때는 문장 끝에서 잘린다", news._cap(long).endswith("."))
    check("상한 이하 본문은 그대로 둔다",
          news._cap("Short. Body.") == "Short. Body.")

    print("\n[파싱 · 길이 필터]")
    url = news.SOURCES[1].feeds["world"]     # NPR world url as a stand-in
    orig = with_feeds({url: RSS})
    arts, err = news.fetch(["npr"], ["world"], 10, rng=random.Random(1))
    news._fetch_feed = orig
    check("오류 없음", err == "", err)
    titles = {a.title for a in arts}
    check("정상 기사 2편만 (너무 짧은 건 제외)", len(arts) == 2, f"({len(arts)}편)")
    check("엔티티가 제목에서 풀린다", "First & foremost" in titles, str(titles))
    check("content:encoded 본문이 캡션 없이 온다",
          any("real body starts" in a.text and "Getty" not in a.text for a in arts))
    check("링크가 채워진다", all(a.url.startswith("http") for a in arts))

    print("\n[VOA: 요약 대신 기사 페이지 본문]")
    check("VOA 소스는 페이지 본문을 가져오도록 표시됨",
          news.SOURCE_BY_KEY["voa"].fetch_page is True)
    page = ('<html><body><div class="body-container">'
            '<div id="article-content" class="wsw fb-quotable">'
            '<p>PARIS &mdash; A rocket roared skyward on Thursday morning.</p>'
            '<p>It took off smoothly and disappeared into the clouds above.</p>'
            '<p>The mission was to deliver a satellite into a high orbit.</p>'
            '</div></div>'
            '<div class="c-mmp">related junk that must not be scraped</div>'
            '</body></html>')
    orig_ff = news._fetch_feed
    news._fetch_feed = lambda u: page.encode("utf-8")
    body = news._article_body("https://www.voanews.com/a/x/1.html")
    news._fetch_feed = orig_ff
    check("본문 문단들이 추출된다", "roared skyward" in body and "high orbit" in body,
          body[:60])
    check("관련기사 위젯은 제외된다", "related junk" not in body)
    check("태그 속성 잔재가 없다", "wsw" not in body and 'class=' not in body)
    check("엔티티가 풀린다", "—" in body)

    print("\n[중복 방지]")
    orig = with_feeds({url: RSS})
    seen = {"g-a"}
    arts2, _ = news.fetch(["npr"], ["world"], 10, seen=seen, rng=random.Random(1))
    news._fetch_feed = orig
    check("이미 본 기사는 빠진다", all(a.guid != "g-a" for a in arts2),
          str([a.guid for a in arts2]))

    print("\n[오프라인 · 빈 결과]")
    orig = news._fetch_feed
    news._fetch_feed = lambda u: (_ for _ in ()).throw(OSError("no net"))
    _, e_off = news.fetch(["npr"], ["world"], 5)
    news._fetch_feed = orig
    check("연결 실패는 news_offline", e_off == "news_offline", e_off)

    orig = with_feeds({url: "<rss><channel></channel></rss>"})
    _, e_empty = news.fetch(["npr"], ["world"], 5)
    news._fetch_feed = orig
    check("받았지만 새 기사 없으면 news_empty", e_empty == "news_empty", e_empty)

    print("\n[테마 가용성]")
    check("모든 매체가 5개 테마를 지원한다",
          all(set(news.available_themes([s.key])) == set(news.THEMES)
              for s in news.SOURCES),
          str({s.key: news.available_themes([s.key]) for s in news.SOURCES}))
    check("The Conversation 단독으로도 science 선택 가능",
          "science" in news.available_themes(["conversation"]),
          str(news.available_themes(["conversation"])))
    check("The Conversation science 는 environment 피드로 매핑",
          "environment" in news.SOURCE_BY_KEY["conversation"].feeds["science"])

    print("\n[면책 동의 게이트]")
    from app.ui.news_import import NewsDisclaimerDialog, NewsImportDialog
    check("처음엔 동의 전 상태", not NewsDisclaimerDialog.already_agreed())
    gate = NewsDisclaimerDialog()
    check("동의 전 '계속' 버튼 비활성", not gate.ok.isEnabled())
    gate.agree.setChecked(True)
    check("동의 체크하면 활성화", gate.ok.isEnabled())
    gate._accept()
    check("동의가 기억된다", NewsDisclaimerDialog.already_agreed())
    gate.deleteLater()

    print("\n[가져온 기사가 지문·출처로 저장된다]")
    print("\n[다이얼로그 기본값 · 과학 · 개수 조절]")
    fresh = NewsImportDialog()
    default_sources = [k for k, c in fresh.source_checks.items() if c.isChecked()]
    check("기본 매체는 1개", len(default_sources) == 1, str(default_sources))
    check("모든 주제가 선택 가능(과학 포함)",
          all(c.isEnabled() for c in fresh.theme_checks.values()))
    check("과학이 The Conversation 단독으로도 가능",
          "science" in news.available_themes(["conversation"]))
    check("개수 기본 1", fresh._count_value == 1)
    check("기본 1이면 − 버튼 비활성", not fresh.minus_btn.isEnabled())
    fresh._step_count(1)
    check("+ 로 2", fresh._count_value == 2 and fresh.count_label.text() == "2")
    for _ in range(20):
        fresh._step_count(-1)
    check("− 는 최소 1에서 멈춘다", fresh._count_value == 1)
    check("최소에서 − 버튼 비활성", not fresh.minus_btn.isEnabled())
    for _ in range(30):
        fresh._step_count(1)
    check("+ 는 최대 20에서 멈춘다", fresh._count_value == 20)
    fresh.deleteLater()

    orig = with_feeds({url: RSS})
    dlg = NewsImportDialog()
    for k, c in dlg.source_checks.items():
        c.setChecked(k == "npr")
    for k, c in dlg.theme_checks.items():
        c.setChecked(k == "world")
    # run the fetch synchronously by calling the worker path directly
    arts3, err3 = news.fetch(["npr"], ["world"], 10, rng=random.Random(2))
    dlg._on_done(arts3, err3)
    news._fetch_feed = orig
    check("지문이 만들어졌다", dlg.created == 2, f"({dlg.created})")
    passages = repo.list_rows("passages", limit=50)
    check("지문에 출처 링크가 저장된다",
          all(repo.get_row("passages", p["id"]).get("source_url", "").startswith("http")
              for p in passages), str(len(passages)))
    a_pass = repo.get_row("passages", passages[0]["id"])
    check("출처·테마가 태그에 담긴다", "NPR" in a_pass["tags"], a_pass["tags"])
    check("본문이 문장으로 나뉜다", len(repo.passage_lines(passages[0]["id"])) >= 1)
    check("다시 가져오면 같은 기사는 안 온다 (seen 기록)",
          all(a.guid not in repo.seen_article_guids()
              for a in news.fetch(["npr"], ["world"], 5,
                                  seen=repo.seen_article_guids())[0]))
    dlg.deleteLater()

    print("\n[가져오는 중에 Esc 로 닫으면 아무것도 만들지 않는다]")
    before_n = repo.count_rows("passages")
    dlg2 = NewsImportDialog()
    dlg2._fetching = True          # a worker is in flight
    dlg2.reject()                  # what Esc and ✕ call
    dlg2._on_done(arts3, "")       # the worker finishes afterwards
    check("취소된 가져오기는 지문을 만들지 않는다",
          repo.count_rows("passages") == before_n and dlg2.created == 0,
          f"({before_n} → {repo.count_rows('passages')})")
    dlg2.deleteLater()

    print("\n[면책 문구가 핵심을 담고 있는지 (정책)]")
    from app import i18n
    for lang in ("ko", "en"):
        i18n.set_language(lang)
        body = i18n.t("news_disclaimer_body")
        needed = (["개인", "저작권", "책임", "재배포"] if lang == "ko"
                  else ["personal", "copyright", "responsib", "redistribute"])
        check(f"{lang}: 개인학습·저작권·책임·재배포 언급",
              all(w in body for w in needed),
              str([w for w in needed if w not in body]))
    i18n.set_language("ko")

    print("\n[실제 피드 한 번 -- 모양 확인]")
    live, err_live = news.fetch(["npr"], ["world"], 3)
    if err_live == "news_offline":
        print("  건너뜀: 네트워크 없음")
    else:
        check("실제로 기사가 온다", len(live) >= 1, f"({len(live)}편, err={err_live})")
        check("제목과 본문이 있다",
              all(a.title and len(a.text) >= 30 for a in live))

    db.close()
    shutil.rmtree(_ROOT, ignore_errors=True)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 뉴스 가져오기 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
