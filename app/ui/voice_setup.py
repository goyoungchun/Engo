"""First-run download of the speech models.

The program is useful without them -- the 🔊 buttons simply stay hidden -- so
this asks rather than downloading unannounced, and it says how large the
download is before starting it. Declining is remembered, with a way back in
from the Data tab.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar, QVBoxLayout,
)

from .. import db, tts
from ..i18n import t

SKIP_KEY = "voices_prompt_skipped"


def should_offer() -> bool:
    """Ask only when something is actually missing and the user has not said no."""
    return bool(tts.missing_defaults()) and db.get_meta(SKIP_KEY, "") != "1"


def remember_skip() -> None:
    db.set_meta(SKIP_KEY, "1")


def clear_skip() -> None:
    db.set_meta(SKIP_KEY, "")


class DownloadDialog(QDialog):
    """Downloads on a worker thread and reports progress on the GUI thread."""

    _progress = Signal(int, int, str)
    _finished = Signal(bool, str)

    def __init__(self, voices, parent=None):
        super().__init__(parent)
        self.voices = list(voices)
        self._stop = False
        self._thread = None
        self.ok = False

        self.setWindowTitle(t("voices_title"))
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        self.message = QLabel(t("voices_downloading"))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        layout.addWidget(self.bar)

        self.detail = QLabel("")
        self.detail.setObjectName("hint")
        layout.addWidget(self.detail)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText(t("cancel"))
        buttons.rejected.connect(self._cancel)
        layout.addWidget(buttons)

        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    def start(self) -> None:
        def report(done, total, name):
            try:
                self._progress.emit(done, total, name)
            except RuntimeError:
                pass          # dialog destroyed; download() will stop via _stop

        def work():
            ok, message = tts.download(
                self.voices, progress=report, should_stop=lambda: self._stop)
            try:
                self._finished.emit(ok, message)
            except RuntimeError:
                pass

        self._thread = threading.Thread(target=work, daemon=True,
                                        name="voice-download")
        self._thread.start()

    def _cancel(self) -> None:
        self._stop = True
        self.detail.setText(t("voices_cancelling"))

    def reject(self) -> None:
        """Every way out -- Cancel button, Esc, the title-bar ✕ -- must stop
        the worker. Before this override, Esc closed the dialog while the
        thread kept downloading; a second attempt then had two writers on the
        same .part file, interleaving them into a corrupt model.
        """
        if self._thread is not None and self._thread.is_alive():
            self._cancel()
            return          # stay open; _on_finished closes us
        super().reject()

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.bar.setValue(int(done * 100 / total) if total else 0)
        self.detail.setText(
            f"{name}   {done / 1024 / 1024:,.0f} / {total / 1024 / 1024:,.0f} MB")

    def _on_finished(self, ok: bool, message: str) -> None:
        self.ok = ok
        self._thread = None      # lets reject()/closeEvent() actually close
        if not ok and message != "cancelled":
            QMessageBox.warning(self, t("voices_title"),
                                t("voices_failed", err=message))
        self.accept() if ok else super().reject()


def offer(parent=None) -> bool:
    """Ask, then download. Returns True if the voices are now available."""
    missing = tts.missing_defaults()
    if not missing:
        return True

    size_mb = tts.download_bytes(missing) / 1024 / 1024
    box = QMessageBox(parent)
    box.setWindowTitle(t("voices_title"))
    box.setText(t("voices_ask", size=f"{size_mb:,.0f}"))
    box.setInformativeText(t("voices_ask_detail"))
    yes = box.addButton(t("voices_download"), QMessageBox.AcceptRole)
    later = box.addButton(t("voices_later"), QMessageBox.RejectRole)
    never = box.addButton(t("voices_never"), QMessageBox.DestructiveRole)
    box.setDefaultButton(yes)
    box.exec()

    clicked = box.clickedButton()
    if clicked is never:
        remember_skip()
        return False
    if clicked is later:
        return False

    dialog = DownloadDialog(missing, parent)
    dialog.start()
    dialog.exec()
    return dialog.ok
