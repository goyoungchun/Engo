"""What changed, shown before anything is installed.

Updating rewrites the program folder, so it should not happen because
someone clicked a button labelled "install" and found out afterwards. This
puts the release notes in front of the decision: here is the version you are
on, here is the one on offer, here is what it changes -- update now, or not.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..i18n import t


class UpdateNotesDialog(QDialog):
    """Release notes plus the choice to go ahead. exec() -> Accepted/Rejected."""

    def __init__(self, current: str, latest: str, notes: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("update_notes_title"))
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        self.heading = QLabel(t("update_notes_versions",
                                current=current, latest=latest.lstrip("v")))
        self.heading.setObjectName("cardTitle")
        outer.addWidget(self.heading)

        outer.addWidget(QLabel(t("update_whats_new")))

        # Read-only rather than a label: notes are written by whoever cut the
        # release and can run to any length, so they get to scroll.
        self.notes = QPlainTextEdit(notes.strip() or t("update_no_notes"))
        self.notes.setReadOnly(True)
        self.notes.setMinimumHeight(140)
        outer.addWidget(self.notes)

        hint = QLabel(t("update_notes_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        outer.addWidget(hint)

        row = QHBoxLayout()
        row.addStretch(1)
        self.later_btn = QPushButton(t("update_later"), self)
        self.later_btn.clicked.connect(self.reject)
        row.addWidget(self.later_btn)
        self.go_btn = QPushButton(t("update_now"), self)
        self.go_btn.setObjectName("primary")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self.accept)
        row.addWidget(self.go_btn)
        outer.addLayout(row)

        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
