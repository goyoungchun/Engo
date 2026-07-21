"""Fetch recent articles as reading passages.

Two dialogs. The first states, plainly, what this is for and who carries the
responsibility -- shown once, agreed to once. The second does the fetching,
off the GUI thread so the window never freezes on a slow feed, and keeps a
one-line reminder of that responsibility in view every time.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .. import db, news, repo
from ..i18n import t
from .common import hint_label


class NewsDisclaimerDialog(QDialog):
    """Shown before the first fetch. Agreement is required and remembered."""

    META_KEY = "news_agreed"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("news_disclaimer_title"))
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(14)

        body = QPlainTextEdit(t("news_disclaimer_body"))
        body.setReadOnly(True)
        body.setMinimumHeight(210)
        outer.addWidget(body)

        self.agree = QCheckBox(t("news_agree"))
        self.agree.toggled.connect(self._on_toggle)
        outer.addWidget(self.agree)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(t("cancel"), self)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.ok = QPushButton(t("news_disclaimer_ok"), self)
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)          # only once the box is ticked
        self.ok.clicked.connect(self._accept)
        row.addWidget(self.ok)
        outer.addLayout(row)

    def _on_toggle(self, checked: bool) -> None:
        self.ok.setEnabled(checked)

    def _accept(self) -> None:
        db.set_meta(self.META_KEY, "1")
        self.accept()

    @staticmethod
    def already_agreed() -> bool:
        return db.get_meta(NewsDisclaimerDialog.META_KEY, "") == "1"


class NewsImportDialog(QDialog):
    """Pick sources and themes, fetch, and turn the results into passages."""

    _done = Signal(object, str)            # (articles, error key)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("fetch_news_title"))
        self.setMinimumWidth(480)
        self._fetching = False
        self._cancelled = False
        self.created = 0
        self._done.connect(self._on_done)
        self._build()

    def reject(self) -> None:
        # The cancel button is disabled while fetching, but Esc and the ✕
        # call reject() regardless. The worker cannot be un-sent, so mark the
        # run cancelled and let _on_done discard its result -- otherwise
        # passages appear that the user explicitly walked away from.
        self._cancelled = True
        super().reject()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        intro = QLabel(t("news_intro"))
        intro.setWordWrap(True)
        outer.addWidget(intro)

        # The responsibility, restated every time in one line.
        reminder = QLabel("⚖  " + t("news_disclaimer_reminder"))
        reminder.setObjectName("hint")
        reminder.setWordWrap(True)
        outer.addWidget(reminder)

        # Sources -- one on by default (the fullest text), the rest a choice.
        src_box = QGroupBox(t("news_sources"))
        src_grid = QGridLayout(src_box)
        self.source_checks: dict[str, QCheckBox] = {}
        for i, source in enumerate(news.SOURCES):
            check = QCheckBox(f"{source.name}  ·  {t(source.licence_key)}")
            check.setChecked(i == 0)
            check.toggled.connect(self._sync_theme_availability)
            self.source_checks[source.key] = check
            src_grid.addWidget(check, i, 0)
        outer.addWidget(src_box)

        # Themes
        theme_box = QGroupBox(t("news_themes"))
        theme_grid = QGridLayout(theme_box)
        self.theme_checks: dict[str, QCheckBox] = {}
        for i, key in enumerate(news.THEMES):
            check = QCheckBox(t(f"theme_{key}"))
            check.setChecked(key in ("world", "technology"))
            self.theme_checks[key] = check
            theme_grid.addWidget(check, i // 3, i % 3)
        outer.addWidget(theme_box)

        # Length -- short / medium / long, by sentence count. All on means any.
        length_box = QGroupBox(t("news_length"))
        length_grid = QGridLayout(length_box)
        self.length_checks: dict[str, QCheckBox] = {}
        for i, key in enumerate(news.LENGTHS):
            check = QCheckBox(t(f"len_{key}"))
            check.setChecked(True)
            self.length_checks[key] = check
            length_grid.addWidget(check, 0, i)
        outer.addWidget(length_box)

        # Count -- explicit − / + buttons around the number, which reads more
        # plainly than a spin box's tiny arrows.
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel(t("news_count")))
        self._count_value = 1
        # Plain buttons, so they share the exact shape of every other button.
        # No jelly reaches them: this dialog is never handed to effects.install.
        self.minus_btn = QPushButton("−", self)   # a real minus sign
        self.minus_btn.clicked.connect(lambda: self._step_count(-1))
        count_row.addWidget(self.minus_btn)
        self.count_label = QLabel(str(self._count_value))
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setFixedWidth(40)
        self.count_label.setObjectName("countValue")
        count_row.addWidget(self.count_label)
        self.plus_btn = QPushButton("+", self)
        self.plus_btn.clicked.connect(lambda: self._step_count(1))
        count_row.addWidget(self.plus_btn)
        self._step_count(0)          # set the initial enabled/disabled state
        count_row.addStretch(1)
        outer.addLayout(count_row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        self.status = hint_label()
        outer.addWidget(self.status)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton(t("cancel"), self)
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        self.fetch_btn = QPushButton(t("news_fetch_btn"), self)
        self.fetch_btn.setObjectName("primary")
        self.fetch_btn.clicked.connect(self._fetch)
        row.addWidget(self.fetch_btn)
        outer.addLayout(row)

        self._sync_theme_availability()

    _COUNT_MIN, _COUNT_MAX = 1, 20

    def _step_count(self, delta: int) -> None:
        self._count_value = max(self._COUNT_MIN,
                                min(self._COUNT_MAX, self._count_value + delta))
        self.count_label.setText(str(self._count_value))
        self.minus_btn.setEnabled(self._count_value > self._COUNT_MIN)
        self.plus_btn.setEnabled(self._count_value < self._COUNT_MAX)

    def _sync_theme_availability(self) -> None:
        """Grey out a theme no chosen source carries, so it cannot mislead."""
        chosen = [k for k, c in self.source_checks.items() if c.isChecked()]
        available = set(news.available_themes(chosen))
        for key, check in self.theme_checks.items():
            ok = key in available
            check.setEnabled(ok)
            if not ok:
                check.setChecked(False)

    # -- fetching --------------------------------------------------------
    def _fetch(self) -> None:
        if self._fetching:
            return
        sources = [k for k, c in self.source_checks.items() if c.isChecked()]
        themes = [k for k, c in self.theme_checks.items()
                  if c.isChecked() and c.isEnabled()]
        if not sources or not themes:
            self.status.setText(t("news_need_pick"))
            return

        self._fetching = True
        self.fetch_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress.setRange(0, 0)       # indeterminate
        self.progress.setVisible(True)
        self.status.setText(t("news_fetching"))

        count = self._count_value
        seen = repo.seen_article_guids()
        # All (or none) checked means "any length" -- pass None so nothing is
        # filtered out and no extra page fetches are spent looking for a match.
        lengths = [k for k, c in self.length_checks.items() if c.isChecked()]
        if len(lengths) == len(news.LENGTHS):
            lengths = None

        def work():
            articles, error = news.fetch(sources, themes, count, seen=seen,
                                         lengths=lengths)
            try:
                self._done.emit(articles, error)
            except RuntimeError:
                pass          # dialog closed while fetching
        threading.Thread(target=work, daemon=True, name="news-fetch").start()

    def _on_done(self, articles, error: str) -> None:
        self._fetching = False
        if self._cancelled:
            return          # closed mid-fetch: nothing may be created
        self.progress.setVisible(False)
        self.fetch_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

        if error:
            self.status.setText(t(error))
            return

        # Create a passage per article, tagged with source and theme, and
        # remember the guids so the same article is not fetched again.
        for article in articles:
            tags = f"{article.source_name}, {t('theme_' + article.theme)}"
            repo.create_passage(article.title, article.text, tags=tags,
                                source_url=article.url)
        repo.mark_articles_seen([a.guid for a in articles])
        self.created = len(articles)
        self.accept()
