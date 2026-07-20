"""Editor for the four voice slots.

Each slot is a name plus a Piper voice. The shipped four are a starting point,
not a fixed list -- any slot can be pointed at a different voice from the
catalogue and renamed, which is why the speech menu reads whatever the slots
happen to say rather than a hard-coded set of genders.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .. import i18n, tts
from ..i18n import t
from . import voice_setup


def _catalogue_label(model: str, quality: str, size_mb: int) -> str:
    return f"{model} · {quality} · {size_mb}MB"


def _find_model(combo, model: str, quality: str) -> int:
    """Index of a (model, quality) entry, or -1.

    QComboBox.findData does not match a Python tuple stored as item data, so
    it silently reported "not found" and the dialog appended a duplicate entry
    for the voice already selected.
    """
    for i in range(combo.count()):
        if combo.itemData(i) == (model, quality):
            return i
    return -1


class VoiceSlotsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("slots_title"))
        self.setMinimumWidth(660)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        intro = QLabel(t("slots_intro"))
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        outer.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for column, key in enumerate(("slots_col_name", "", "slots_col_model",
                                      "slots_col_state", "")):
            label = QLabel(t(key) if key else "")
            label.setStyleSheet("font-weight: 600;")
            grid.addWidget(label, 0, column)

        self.rows: dict[str, dict] = {}
        for row, key in enumerate(tts.SLOT_KEYS, start=1):
            voice = tts.VOICES[key]

            name = QLineEdit(voice.label(i18n.language()))
            grid.addWidget(name, row, 0)

            # Sits right beside the name, so it is obvious which four slots
            # hold the voices the program ships with.
            factory = QLabel()
            factory.setObjectName("hint")
            grid.addWidget(factory, row, 1)

            model = QComboBox()
            for cat_model, quality, size in tts.CATALOGUE:
                model.addItem(_catalogue_label(cat_model, quality, size),
                              (cat_model, quality))
            index = _find_model(model, voice.model, voice.quality)
            if index < 0:      # a voice the catalogue does not list
                model.addItem(f"{voice.model} · {voice.quality}",
                              (voice.model, voice.quality))
                index = model.count() - 1
            model.setCurrentIndex(index)
            model.setMinimumWidth(210)
            grid.addWidget(model, row, 2)

            state = QLabel()
            grid.addWidget(state, row, 3)

            get = QPushButton(t("slots_get"))
            get.clicked.connect(lambda _=False, k=key: self._download(k))
            grid.addWidget(get, row, 4)

            self.rows[key] = {"name": name, "model": model, "state": state,
                              "get": get, "factory": factory}
            model.currentIndexChanged.connect(
                lambda _=0, k=key: self._refresh_row(k))

        outer.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.Reset)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Ok).setText(t("save"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("cancel"))
        buttons.button(QDialogButtonBox.Reset).setText(t("slots_reset"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._reset)
        outer.addWidget(buttons)

        self._refresh_all()

    # -- state ------------------------------------------------------------
    def _pending(self, key: str) -> tts.Voice:
        """What the slot would become with the current form contents."""
        row = self.rows[key]
        base = tts.VOICES[key]
        # A combo with no selection returns None. That happens whenever the
        # index is set to something that is not in the list, and unpacking it
        # blindly took the whole dialog down.
        data = row["model"].currentData()
        model, quality = data if data else (base.model, base.quality)
        return tts.Voice(key=key, gender=base.gender, model=model,
                         quality=quality, name_ko=row["name"].text().strip(),
                         name_en=row["name"].text().strip(), default=base.default)

    def _refresh_row(self, key: str) -> None:
        row = self.rows[key]
        voice = self._pending(key)
        ready = voice.exists()
        row["state"].setText(t("slots_ready") if ready else t("slots_not_ready"))
        row["get"].setVisible(not ready)
        base = tts.FACTORY_SLOTS[key]
        is_factory = (voice.model, voice.quality) == (base.model, base.quality)
        row["factory"].setText(t("default_mark") if is_factory else "")

    def _refresh_all(self) -> None:
        for key in tts.SLOT_KEYS:
            self._refresh_row(key)

    # -- actions ----------------------------------------------------------
    def _download(self, key: str) -> None:
        voice = self._pending(key)
        if voice.exists():
            return
        dialog = voice_setup.DownloadDialog([voice], self)
        dialog.start()
        dialog.exec()
        if not dialog.ok and voice.exists() is False:
            pass          # the dialog already explained why
        self._refresh_row(key)

    def _save(self) -> None:
        missing = []
        for key in tts.SLOT_KEYS:
            voice = self._pending(key)
            if not voice.label("ko"):
                QMessageBox.information(self, t("slots_title"), t("slots_need_name"))
                return
            if not voice.exists():
                missing.append(voice.label("ko"))

        for key in tts.SLOT_KEYS:
            # Through _pending, which copes with an unselected combo.
            voice = self._pending(key)
            tts.save_slot(key, voice.label("ko"), voice.model, voice.quality,
                          voice.gender)

        if missing:
            QMessageBox.information(
                self, t("slots_title"), t("slots_saved_missing",
                                          names=", ".join(missing)))
        self.accept()

    def _reset(self) -> None:
        for key in tts.SLOT_KEYS:
            tts.reset_slot(key)
        for key in tts.SLOT_KEYS:
            voice = tts.VOICES[key]
            row = self.rows[key]
            row["name"].setText(voice.label(i18n.language()))
            index = _find_model(row["model"], voice.model, voice.quality)
            if index >= 0:
                row["model"].setCurrentIndex(index)
        self._refresh_all()


