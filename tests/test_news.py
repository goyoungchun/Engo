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

    print("\n[데이트라인이 다음 문장과 합쳐진다]")
    # A news dateline sits on its own line in the source HTML; it must join the
    # sentence it introduces, not stand alone.
    dl = repo.split_sentences(news.clean(
        "<p>CAPE CANAVERAL, Florida &mdash; \n A company launched a lander "
        "Wednesday, aiming for the south pole.</p><p>It carried a drone.</p>"))
    check("데이트라인이 첫 문장에 붙는다",
          dl[0].startswith("CAPE CANAVERAL, Florida — A company"), repr(dl[0]))
    check("문장은 마침표 기준으로만 나뉜다", len(dl) == 2, str(dl))
    # ...while a heading still stands on its own line
    hd = repo.split_sentences(news.clean(
        "<p>Body one.</p><h2>Section</h2><p>Body two.</p>"))
    check("소제목은 여전히 별도 줄", "## Section" in hd, str(hd))
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
    check("NPR 도 페이지 본문을 가져온다", news.SOURCE_BY_KEY["npr"].fetch_page)
    check("VOA 는 본문 없는 페이지를 버린다",
          news.SOURCE_BY_KEY["voa"].drop_if_no_body)

    print("\n[이미지 캡션/크레딧 제거]")
    cap_page = ('<div id="storytext">'
                '<div class="bucketwrap image"><picture><img alt="a photo" /></picture>'
                '<div class="credit-caption"><div class="caption">'
                '<p>A protester marches in the street. '
                '<b class="credit">Vipin/AP</b></p></div></div></div>'
                '<p>NEW DELHI — The real article starts here and continues on.</p>'
                '<p>The tax credit helped families this year.</p></div>')
    orig_ff2 = news._fetch_feed
    news._fetch_feed = lambda u: cap_page.encode("utf-8")
    npr_body = news._article_body("https://www.npr.org/x")
    news._fetch_feed = orig_ff2
    check("이미지 캡션이 첫 문장이 되지 않는다",
          npr_body.startswith("NEW DELHI"), npr_body[:40])
    check("'credit'라는 단어가 든 본문 문장은 살아남는다",
          "tax credit helped" in npr_body)
    check("(Image credit:...) 는 제거된다",
          "Image credit" not in news.clean(
              "Body here. (Image credit: Vipin)"))

    print("\n[관련기사 광고 · 편집자 푸터 제외 -- 제목/부제목/본문만]")
    npr_page = (
        '<div id="storytext">'
        '<p>NEW YORK — Federal regulators are in settlement talks today.</p>'
        '<h2 class="edTag">A real subheading of the article</h2>'
        '<p>The market has grown quickly over the past year and a half.</p>'
        # a related-story recirculation promo -- must be dropped
        '<h3 class="slug"><a href="/sections/technology/">Technology</a></h3>'
        '<h3><a data-metrics-ga4=\'{"category":"recirculation"}\'>'
        'TV antennas and Super Bowl rehearsals</a></h3>'
        '<p>She still enjoys learning; a listen to music helps her focus.</p>'
        # the editorial footer -- must end collection
        '<div class="hr"><hr /></div>'
        '<p><em>The story was edited by Meghan Keane.</em></p>'
        '<p><em>Listen to Life Kit on Apple Podcasts and Spotify.</em></p>'
        '<p><em>Follow us on Instagram: @nprlifekit.</em></p>'
        '</div>')
    orig_ff3 = news._fetch_feed
    news._fetch_feed = lambda u: npr_page.encode("utf-8")
    got = news._article_body("https://www.npr.org/y")
    news._fetch_feed = orig_ff3
    check("본문 첫 문장은 그대로", got.startswith("NEW YORK"), got[:30])
    check("실제 부제목은 유지", "## A real subheading" in got, got)
    check("관련기사 슬러그(Technology)는 제외", "## Technology" not in got)
    check("관련기사 제목(Super Bowl)은 제외", "Super Bowl" not in got)
    check("'listen to music' 본문 문장은 살아남는다", "listen to music helps" in got)
    check("편집자 크레딧은 제외", "edited by" not in got)
    check("팟캐스트/인스타 홍보는 제외",
          "Apple Podcasts" not in got and "Instagram" not in got, got[-60:])

    print("\n[뉴스레터 인트로 제외 · 본문 목록 포함]")
    letter = (
        '<div id="storytext">'
        '<p><em>Good morning. You\'re reading the Up First newsletter. '
        'Subscribe here to get it delivered to your inbox.</em></p>'
        '<h2 class="edTag">3 things to know before you go</h2>'
        '<ol class="edTag">'
        '<li>🎧 British runner Josh Kerr ran a record mile on Saturday.</li>'
        '<li>Andrew Tate was arrested by the U.S. Marshals in Miami.</li>'
        '</ol>'
        '<ul><li><a href="/nav">Some navigation link that is not article</a></li></ul>'
        '</div>')
    orig_ff4 = news._fetch_feed
    news._fetch_feed = lambda u: letter.encode("utf-8")
    letter_body = news._article_body("https://www.npr.org/z")
    news._fetch_feed = orig_ff4
    check("인사말/구독 홍보가 제외된다",
          "Good morning" not in letter_body
          and "delivered to your inbox" not in letter_body, letter_body[:40])
    check("소제목은 유지", "## 3 things to know" in letter_body)
    check("본문 목록 항목이 포함된다",
          "Josh Kerr" in letter_body and "Andrew Tate" in letter_body)
    check("선두 이모지(🎧)는 제거", "🎧" not in letter_body)
    check("네비게이션 목록은 제외", "navigation link" not in letter_body)

    print("\n[지문 길이 분류]")
    check("10문장 이하 short", news.length_category_by_count(6) == "short")
    check("11~25 medium", news.length_category_by_count(18) == "medium")
    check("26 이상 long", news.length_category_by_count(40) == "long")

    print("\n[중복 방지]")
    orig = with_feeds({url: RSS})
    seen = {"g-a"}
    arts2, _ = news.fetch(["npr"], ["world"], 10, seen=seen, rng=random.Random(1))
    news._fetch_feed = orig
    check("이미 본 기사는 빠진다", all(a.guid != "g-a" for a in arts2),
          str([a.guid for a in arts2]))

    print("\n[길이 필터로 가져오기]")
    long_body = " ".join(f"Sentence number {i} here now." for i in range(40))
    feed = ("<rss><channel>"
            "<item><title>Short piece</title><link>https://ex.com/s</link>"
            "<guid>len-s</guid><description>Just one short sentence, but long "
            "enough to clear the minimum length filter comfortably.</description></item>"
            f"<item><title>Long piece</title><link>https://ex.com/l</link>"
            f"<guid>len-l</guid><description>{long_body}</description></item>"
            "</channel></rss>")
    url_len = news.SOURCES[1].feeds["world"]
    orig = with_feeds({url_len: feed})
    short_only, _ = news.fetch(["npr"], ["world"], 5, lengths={"short"},
                              rng=random.Random(1))
    long_only, _ = news.fetch(["npr"], ["world"], 5, lengths={"long"},
                             rng=random.Random(1))
    news._fetch_feed = orig
    check("짧은 글만 요청하면 짧은 것만", [a.guid for a in short_only] == ["len-s"],
          str([a.guid for a in short_only]))
    check("긴 글만 요청하면 긴 것만", [a.guid for a in long_only] == ["len-l"],
          str([a.guid for a in long_only]))

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
    check("길이 선택이 3개(짧음/중간/김)", len(fresh.length_checks) == 3)
    check("길이 기본은 중간만", fresh.length_checks["medium"].isChecked()
          and not fresh.length_checks["short"].isChecked()
          and not fresh.length_checks["long"].isChecked())
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
