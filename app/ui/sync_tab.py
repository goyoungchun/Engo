"""데이터 관리 — export, import/merge, CSV, backup.

This is the whole "move my study data to another PC" story: write a file here,
copy it however you like (USB, cloud drive, email), read it there.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import db, repo, sync, theme
from ..i18n import t
from .common import hint_label, scrollable


def _stamp(ms: int) -> str:
    if not ms:
        return t("none")
    return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


class SyncTab(QWidget):
    dataChanged = Signal()

    def __init__(self, palette: theme.Palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self._build()
        self.retranslate()
        self.reload()

    def _build(self) -> None:
        # The four boxes plus the log need more height than a 720px window
        # has. Without a scroll area Qt squeezes them, and the import row --
        # the tallest -- collapsed to a few pixels of overlapping slivers.
        page = QWidget()
        inner = QVBoxLayout(page)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(14)

        for box in (self._build_device_box(), self._build_export_box(),
                    self._build_import_box(), self._build_extra_box()):
            box.setSizePolicy(box.sizePolicy().horizontalPolicy(),
                              QSizePolicy.Fixed)
            inner.addWidget(box)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        inner.addWidget(self.log)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(page))

    # -- boxes -----------------------------------------------------------
    def _build_device_box(self) -> QGroupBox:
        self.device_box = QGroupBox()
        layout = QHBoxLayout(self.device_box)
        layout.setSpacing(10)

        self.device_name_label = QLabel()
        layout.addWidget(self.device_name_label)
        self.device_name = QLineEdit()
        self.device_name.setMaximumWidth(230)
        self.device_name.editingFinished.connect(self._save_device_name)
        layout.addWidget(self.device_name)

        self.device_info = hint_label()
        layout.addWidget(self.device_info, 1)
        return self.device_box

    def _build_export_box(self) -> QGroupBox:
        self.export_box_widget = QGroupBox()
        layout = QVBoxLayout(self.export_box_widget)
        layout.setSpacing(9)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.export_mode = QComboBox()
        self.export_mode.addItem("", 0)
        self.export_mode.addItem("", 1)
        row.addWidget(self.export_mode, 1)

        self.export_btn = QPushButton()
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export_file)
        row.addWidget(self.export_btn)
        layout.addLayout(row)

        self.export_hint = hint_label()
        self.export_hint.setWordWrap(True)
        layout.addWidget(self.export_hint)
        return self.export_box_widget

    def _build_import_box(self) -> QGroupBox:
        self.import_box_widget = QGroupBox()
        layout = QVBoxLayout(self.import_box_widget)
        layout.setSpacing(9)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.import_path = QLineEdit()
        self.import_path.setReadOnly(True)
        row.addWidget(self.import_path, 1)

        self.browse_btn = QPushButton()
        self.browse_btn.clicked.connect(self.choose_import)
        row.addWidget(self.browse_btn)

        self.preview_btn = QPushButton()
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(lambda: self.import_file(dry_run=True))
        row.addWidget(self.preview_btn)

        self.merge_btn = QPushButton()
        self.merge_btn.setObjectName("primary")
        self.merge_btn.setEnabled(False)
        self.merge_btn.clicked.connect(lambda: self.import_file(dry_run=False))
        row.addWidget(self.merge_btn)
        layout.addLayout(row)

        self.backup_first = QCheckBox()
        self.backup_first.setChecked(True)
        layout.addWidget(self.backup_first)

        self.rule_label = hint_label()
        self.rule_label.setWordWrap(True)
        self.rule_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.rule_label)
        return self.import_box_widget

    def _build_extra_box(self) -> QGroupBox:
        self.extra_box_widget = QGroupBox()
        layout = QHBoxLayout(self.extra_box_widget)
        layout.setSpacing(8)

        self.csv_table = QComboBox()
        for key in ("expressions", "sentences", "grammar"):
            self.csv_table.addItem("", key)
        layout.addWidget(self.csv_table)

        self.csv_out_btn = QPushButton()
        self.csv_out_btn.clicked.connect(self.export_csv)
        layout.addWidget(self.csv_out_btn)

        self.csv_in_btn = QPushButton()
        self.csv_in_btn.clicked.connect(self.import_csv)
        layout.addWidget(self.csv_in_btn)

        layout.addStretch(1)

        self.backup_btn = QPushButton()
        self.backup_btn.clicked.connect(self.backup_now)
        layout.addWidget(self.backup_btn)

        self.purge_btn = QPushButton()
        self.purge_btn.clicked.connect(self.purge)
        layout.addWidget(self.purge_btn)
        return self.extra_box_widget

    # -- language --------------------------------------------------------
    def retranslate(self) -> None:
        self.device_box.setTitle(t("this_device"))
        self.device_name_label.setText(t("device_name"))

        self.export_box_widget.setTitle(t("export_box"))
        self.export_mode.setItemText(0, t("export_full"))
        self.export_mode.setItemText(1, t("export_incremental"))
        self.export_btn.setText(t("export_button"))

        self.import_box_widget.setTitle(t("import_box"))
        self.import_path.setPlaceholderText(t("ph_import"))
        self.browse_btn.setText(t("choose_file"))
        self.preview_btn.setText(t("preview_merge"))
        self.merge_btn.setText(t("do_merge"))
        self.backup_first.setText(t("backup_first"))
        self.rule_label.setText(t("merge_rule"))

        self.extra_box_widget.setTitle(t("other_box"))
        for i, key in enumerate(("kind_expressions", "kind_sentences", "gram_title")):
            self.csv_table.setItemText(i, t(key))
        self.csv_out_btn.setText(t("export_csv"))
        self.csv_in_btn.setText(t("import_csv"))
        self.csv_in_btn.setToolTip(t("import_csv_tip"))
        self.backup_btn.setText(t("backup_now"))
        self.purge_btn.setText(t("purge"))
        self.purge_btn.setToolTip(t("purge_tip"))
        self.log.setPlaceholderText(t("log_placeholder"))
        self.reload()

    def restyle(self, p: theme.Palette) -> None:
        self.palette = p

    # -- state -----------------------------------------------------------
    def reload(self) -> None:
        self.device_name.setText(db.get_meta("device_name"))
        size = db.db_path().stat().st_size / 1024 if db.db_path().exists() else 0
        self.device_info.setText(t("device_info", id=db.device_id(),
                                   path=db.db_path(), size=f"{size:,.0f}"))
        last = int(db.get_meta("last_export_at", "0") or 0)
        self.export_hint.setText(t("export_hint", when=_stamp(last)))

    def _save_device_name(self) -> None:
        db.set_meta("device_name", self.device_name.text().strip() or "PC")
        self.reload()

    def _log(self, text: str) -> None:
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")

    # -- export ----------------------------------------------------------
    def export_file(self) -> None:
        default = (Path.home() / "Documents" /
                   f"Engo_{db.get_meta('device_name')}_"
                   f"{_dt.date.today().isoformat()}.seb")
        path, _ = QFileDialog.getSaveFileName(
            self, t("export_dialog"), str(default), t("filter_export"))
        if not path:
            return

        since = 0
        if self.export_mode.currentData() == 1:
            since = int(db.get_meta("last_export_at", "0") or 0)

        try:
            counts = sync.export_to_file(path, since_ms=since)
        except Exception as exc:
            QMessageBox.critical(self, t("export_failed"), str(exc))
            return

        db.set_meta("last_export_at", db.now_ms())
        self.reload()
        total = sum(counts.values())
        size = Path(path).stat().st_size / 1024
        self._log(t("log_export", n=total, size=f"{size:,.0f}", path=path))
        QMessageBox.information(self, t("export_done"),
                                t("export_done_body", n=total, path=path))

    # -- import ----------------------------------------------------------
    def choose_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("import_dialog"), str(Path.home() / "Documents"),
            t("filter_export"))
        if not path:
            return
        try:
            info = sync.preview_file(path)
        except Exception as exc:
            QMessageBox.critical(self, t("unreadable"), str(exc))
            return

        self.import_path.setText(path)
        self.preview_btn.setEnabled(True)
        self.merge_btn.setEnabled(True)
        self._log(t("log_file_ok",
                    device=info["device_name"] or info["device_id"],
                    when=_stamp(info["exported_at"]),
                    kind=t("kind_partial") if info["incremental"] else t("kind_full"),
                    n=sum(info["counts"].values())))

    def import_file(self, dry_run: bool) -> None:
        path = self.import_path.text().strip()
        if not path:
            return

        if not dry_run and self.backup_first.isChecked():
            try:
                backup = self._auto_backup()
                self._log(t("log_backup", path=backup))
            except Exception as exc:
                answer = QMessageBox.question(
                    self, t("backup_failed"), t("backup_failed_body", err=exc),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    return

        try:
            report = sync.import_file(path, dry_run=dry_run)
        except Exception as exc:
            QMessageBox.critical(self, t("import_failed"), str(exc))
            return

        title = t("merge_preview") if dry_run else t("merge_done")
        body = report.summary() + (t("preview_note") if dry_run else "")
        self._log(t("log_merge", title=title, added=report.total_added,
                    updated=report.total_updated, skipped=report.total_skipped))
        QMessageBox.information(self, title, body)

        if not dry_run:
            self.dataChanged.emit()
            self.reload()

    def _auto_backup(self) -> Path:
        folder = db.default_data_dir() / "backups"
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = sync.backup_database(folder / f"study_{stamp}.db")
        # Keep the ten most recent; older ones are dead weight in AppData.
        for old in sorted(folder.glob("study_*.db"))[:-10]:
            old.unlink(missing_ok=True)
        return path

    # -- extras ----------------------------------------------------------
    def export_csv(self) -> None:
        table = self.csv_table.currentData()
        default = Path.home() / "Documents" / f"{table}_{_dt.date.today().isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, t("export_csv"), str(default), t("filter_csv"))
        if not path:
            return
        count = sync.export_csv(table, path)
        self._log(t("log_csv_out", n=count, path=path))
        QMessageBox.information(self, t("done"), t("csv_done", n=count))

    def import_csv(self) -> None:
        table = self.csv_table.currentData()
        path, _ = QFileDialog.getOpenFileName(
            self, t("import_csv"), str(Path.home() / "Documents"), t("filter_csv"))
        if not path:
            return
        answer = QMessageBox.question(
            self, t("import_csv"),
            t("csv_import_confirm", fields=", ".join(sync.CSV_FIELDS[table])),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        try:
            count = sync.import_csv(table, path)
        except Exception as exc:
            QMessageBox.critical(self, t("import_failed"), str(exc))
            return
        self._log(t("log_csv_in", n=count))
        QMessageBox.information(self, t("done"), t("csv_added", n=count))
        self.dataChanged.emit()

    def backup_now(self) -> None:
        try:
            path = self._auto_backup()
        except Exception as exc:
            QMessageBox.critical(self, t("backup_failed"), str(exc))
            return
        self._log(t("log_backup_done", path=path))
        QMessageBox.information(self, t("backup_done"), str(path))

    def purge(self) -> None:
        answer = QMessageBox.question(
            self, t("purge"), t("purge_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        count = repo.purge_tombstones()
        self._log(t("log_purge", n=count))
        self.reload()

