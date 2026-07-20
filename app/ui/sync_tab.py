"""데이터 관리 — export, import/merge, CSV, backup.

This is the whole "move my study data to another PC" story: write a file here,
copy it however you like (USB, cloud drive, email), read it there.
"""

from __future__ import annotations

import datetime as _dt
import threading
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import db, i18n, repo, sync, theme, tts, uninstall, update
from ..i18n import t
from . import voice_setup
from .common import ResponsiveRow, hint_label, scrollable


def _stamp(ms: int) -> str:
    if not ms:
        return t("none")
    return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


class SyncTab(QWidget):
    dataChanged = Signal()
    updateAvailable = Signal(bool)
    voicesChanged = Signal()
    quitRequested = Signal()
    # Emitted from worker threads; a queued connection hands the result back
    # to the GUI thread, which is the only one allowed to touch widgets.
    _update_done = Signal(object)
    _install_done = Signal(bool, str)

    def __init__(self, palette: theme.Palette, parent=None):
        super().__init__(parent)
        self.palette = palette
        self._checking = False
        self._installing = False
        self._last_check = None
        self._build()
        self._update_done.connect(self._on_update_checked)
        self._install_done.connect(self._on_install_done)
        self.retranslate()
        self.reload()
        # Checked when this tab is first built rather than at start-up: the
        # program should not reach for the network just because it launched.
        self.check_update()

    def _build(self) -> None:
        # The four boxes plus the log need more height than a 720px window
        # has. Without a scroll area Qt squeezes them, and the import row --
        # the tallest -- collapsed to a few pixels of overlapping slivers.
        page = QWidget()
        inner = QVBoxLayout(page)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(14)

        # Two pairs that sit side by side while there is room and stack when
        # the window is narrowed.
        self.status_row = ResponsiveRow(threshold=820)
        for box in (self._build_update_box(), self._build_voices_box()):
            box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            self.status_row.add(box)
        inner.addWidget(self.status_row)

        self._build_device_box().setSizePolicy(QSizePolicy.Preferred,
                                               QSizePolicy.Fixed)
        inner.addWidget(self.device_box)

        self.transfer_row = ResponsiveRow(threshold=940)
        for box in (self._build_export_box(), self._build_import_box()):
            box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            self.transfer_row.add(box)
        inner.addWidget(self.transfer_row)

        extra = self._build_extra_box()
        extra.setSizePolicy(extra.sizePolicy().horizontalPolicy(),
                            QSizePolicy.Fixed)
        inner.addWidget(extra)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        inner.addWidget(self.log)

        # Last, and deliberately below the log: nothing here is reached by
        # accident on the way to something else.
        danger = self._build_uninstall_box()
        danger.setSizePolicy(danger.sizePolicy().horizontalPolicy(),
                             QSizePolicy.Fixed)
        inner.addWidget(danger)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(page))

    # -- boxes -----------------------------------------------------------
    def _build_update_box(self) -> QGroupBox:
        self.update_box_widget = QGroupBox()
        layout = QVBoxLayout(self.update_box_widget)
        layout.setSpacing(9)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.update_status = QLabel()
        self.update_status.setWordWrap(True)
        row.addWidget(self.update_status, 1)

        self.update_check_btn = QPushButton(self.update_box_widget)
        self.update_check_btn.clicked.connect(lambda: self.check_update(quiet=False))
        row.addWidget(self.update_check_btn)

        self.update_apply_btn = QPushButton(self.update_box_widget)
        self.update_apply_btn.setObjectName("primary")
        self.update_apply_btn.clicked.connect(self.apply_update)
        self.update_apply_btn.setVisible(False)
        row.addWidget(self.update_apply_btn)

        self.update_link_btn = QPushButton(self.update_box_widget)
        self.update_link_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(update.WEB)))
        row.addWidget(self.update_link_btn)
        layout.addLayout(row)
        return self.update_box_widget

    def _build_voices_box(self) -> QGroupBox:
        self.voices_box_widget = QGroupBox()
        layout = QVBoxLayout(self.voices_box_widget)
        layout.setSpacing(9)

        self.voices_status = QLabel()
        self.voices_status.setWordWrap(True)
        layout.addWidget(self.voices_status)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        self.voices_get_btn = QPushButton(self.voices_box_widget)
        self.voices_get_btn.setObjectName("primary")
        self.voices_get_btn.clicked.connect(
            lambda: self._download_voices(tts.missing_defaults()))
        row.addWidget(self.voices_get_btn)

        self.voices_extra_btn = QPushButton(self.voices_box_widget)
        self.voices_extra_btn.clicked.connect(
            lambda: self._download_voices(
                [v for v in tts.VOICES.values() if not v.exists()]))
        row.addWidget(self.voices_extra_btn)

        self.voices_settings_btn = QPushButton(self.voices_box_widget)
        self.voices_settings_btn.clicked.connect(self._open_voice_slots)
        row.addWidget(self.voices_settings_btn)
        layout.addLayout(row)
        return self.voices_box_widget

    def _open_voice_slots(self) -> None:
        from .voice_slots import VoiceSlotsDialog
        dialog = VoiceSlotsDialog(self)
        dialog.exec()
        # Refresh regardless of how the dialog closed: a voice downloaded via
        # a slot's 받기 button exists on disk even if the user then cancels.
        self._refresh_voices()
        self.voicesChanged.emit()

    def _download_voices(self, voices) -> None:
        voices = [v for v in voices if not v.exists()]
        if not voices:
            return
        voice_setup.clear_skip()
        dialog = voice_setup.DownloadDialog(voices, self)
        dialog.start()
        dialog.exec()
        self._refresh_voices()
        # Without this the 🔊 buttons and the reading menu stayed hidden
        # until the program was restarted -- the download changed the disk
        # but nothing told the main window about it.
        self.voicesChanged.emit()
        if dialog.ok:
            QMessageBox.information(self, t("voices_title"),
                                    t("voices_ready", n=len(tts.available_voices())))

    def _refresh_voices(self) -> None:
        ready = tts.available_voices()
        missing_defaults = tts.missing_defaults()
        any_missing = [v for v in tts.VOICES.values() if not v.exists()]

        if ready:
            self.voices_status.setText(t("voices_ready", n=len(ready)))
        else:
            self.voices_status.setText(t("voices_missing"))
        self.voices_get_btn.setVisible(bool(missing_defaults))
        self.voices_extra_btn.setVisible(
            bool(any_missing) and not missing_defaults)

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
        # The path can be longer than the window at minimum width; without
        # wrapping it is silently clipped (the page never scrolls sideways).
        self.device_info.setWordWrap(True)
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

    def _build_uninstall_box(self) -> QGroupBox:
        self.uninstall_box_widget = QGroupBox()
        layout = QHBoxLayout(self.uninstall_box_widget)
        layout.setSpacing(12)

        self.uninstall_hint = hint_label("")
        self.uninstall_hint.setWordWrap(True)
        layout.addWidget(self.uninstall_hint, 1)

        self.uninstall_btn = QPushButton(self.uninstall_box_widget)
        self.uninstall_btn.setObjectName("danger")
        self.uninstall_btn.clicked.connect(self.uninstall)
        layout.addWidget(self.uninstall_btn, 0, Qt.AlignVCenter)
        return self.uninstall_box_widget

    # -- language --------------------------------------------------------
    def retranslate(self) -> None:
        self.update_box_widget.setTitle(t("update_box"))
        self.update_check_btn.setText(t("update_check"))
        self.update_apply_btn.setText(t("update_apply"))
        self.update_link_btn.setText(t("open_github"))
        if self._last_check is None and self._checking:
            # A language switch mid-check would otherwise leave the previous
            # language's "checking…" on screen until the check finishes.
            self.update_status.setText(t("update_checking"))

        self.voices_box_widget.setTitle(t("voices_box"))
        self.voices_get_btn.setText(t("voices_get"))
        self.voices_extra_btn.setText(t("voices_get_extra"))
        self.voices_settings_btn.setText(t("voices_settings"))
        self._refresh_voices()
        if self._last_check is not None:
            self._render_update(self._last_check)

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

        self.uninstall_box_widget.setTitle(t("uninstall_box"))
        self.uninstall_hint.setText(t("uninstall_desc"))
        self.uninstall_btn.setText(t("uninstall_btn"))
        self.reload()

    # -- removing the program --------------------------------------------
    def uninstall(self) -> None:
        """Delete Engo's data, and optionally what setup downloaded.

        Two questions, not one. The first is about study data and cannot be
        undone; the second is about a few hundred megabytes of re-downloadable
        components, and answering "no" to it is a perfectly good outcome.
        """
        lang = i18n.language()
        data = uninstall.data_targets()
        parts = uninstall.component_targets()

        if not data and not parts:
            QMessageBox.information(self, t("uninstall_box"), t("uninstall_nothing"))
            return

        def listing(targets) -> str:
            return "\n".join(f"    · {x.label(lang)}   {uninstall.human(x.size)}"
                             for x in targets)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(t("uninstall_confirm_title"))
        box.setText(t("uninstall_confirm_body",
                      items=listing(data) or "    -"))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)     # the safe answer is preselected
        if box.exec() != QMessageBox.Yes:
            return

        # Second, separate consent for the downloaded components.
        remove_parts = False
        if parts:
            kept = uninstall.kept_packages()
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle(t("uninstall_parts_title"))
            box.setText(t("uninstall_parts_body", items=listing(parts),
                          kept=t("uninstall_kept",
                                 items="\n".join(f"    · {k}" for k in kept))
                          if kept else ""))
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            remove_parts = box.exec() == QMessageBox.Yes

        targets = list(data) + (parts if remove_parts else [])

        uninstall.remove_autostart()
        uninstall.close_everything()          # release the db and speech files
        done, failed = uninstall.remove(targets)
        deferred = uninstall.schedule_deferred(targets)
        if remove_parts:
            # Only once the downloaded components are gone. If they were kept,
            # the record of what we downloaded has to survive with them --
            # relaunching still works, and a later removal needs to know.
            uninstall.drop_manifest()

        message = t("uninstall_done_body",
                    items="\n".join(f"    · {x.label(lang)}" for x in done) or "    -")
        if failed:
            message += t("uninstall_failed",
                         items="\n".join(f"    · {x.label(lang)} — {why}"
                                         for x, why in failed))
        if deferred:
            message += t("uninstall_deferred")
        message += t("uninstall_folder", path=uninstall.PROJECT_DIR)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(t("uninstall_done_title"))
        box.setText(message)
        open_btn = box.addButton(t("uninstall_open_folder"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            uninstall.open_folder(uninstall.PROJECT_DIR)

        # The database is gone; there is nothing left for the app to run on.
        self.quitRequested.emit()

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
        try:
            count = sync.export_csv(table, path)
        except OSError as exc:
            # The classic case: the same CSV is open in Excel, which holds it
            # locked. Without this the failure was completely silent under
            # pythonw -- no dialog, no file, no log line.
            QMessageBox.critical(self, t("export_failed"), str(exc))
            return
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
        try:
            # VACUUM needs free disk roughly the size of the database and
            # raises when it cannot get it.
            count = repo.purge_tombstones()
        except Exception as exc:
            QMessageBox.critical(self, t("purge"), str(exc))
            return
        self._log(t("log_purge", n=count))
        self.reload()

    # -- update ----------------------------------------------------------
    def check_update(self, quiet: bool = True) -> None:
        """Ask GitHub whether there is a newer commit.

        Runs on a worker thread: a network call on the GUI thread would freeze
        the window for however long the connection takes to time out.
        """
        if self._checking:
            return
        self._checking = True
        self.update_status.setText(t("update_checking"))
        self.update_check_btn.setEnabled(False)

        def work():
            result = update.check()
            try:
                self._update_done.emit(result)
            except RuntimeError:
                # The tab was destroyed (window closed to tray) while the
                # network call was in flight. Nobody is left to tell.
                pass

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _on_update_checked(self, result) -> None:
        self._checking = False
        self._last_check = result
        self.update_check_btn.setEnabled(True)
        self._render_update(result)
        self.updateAvailable.emit(result.update_available)

    def _render_update(self, result) -> None:
        if result.state == update.AVAILABLE:
            text = t("update_available", latest=result.latest.lstrip("v"),
                     current=result.current)
        elif result.state == update.OFFLINE:
            text = t("update_offline")
        elif result.state == update.ERROR:
            text = t("update_error")
        else:
            text = t("update_latest", current=result.current)

        self.update_status.setText(text)
        self.update_status.setToolTip(
            f"{t('update_whats_new')}\n\n{result.notes}" if result.notes else "")
        self.update_apply_btn.setVisible(result.update_available)
        self.update_link_btn.setVisible(result.state != update.UP_TO_DATE)

    def apply_update(self) -> None:
        """Download and install the newest release, off the GUI thread.

        The archive download can take arbitrarily long on a slow connection,
        so running install() inline would freeze the window for the duration.
        """
        if self._installing:
            return
        self._installing = True
        self.update_apply_btn.setEnabled(False)
        self.update_check_btn.setEnabled(False)
        self.update_status.setText(t("update_downloading"))

        def work():
            # has_local_changes shells out to git; on a cold or broken repo
            # that can stall for seconds, so it belongs off the GUI thread
            # with the rest of the work.
            if update.has_local_changes():
                ok, message = False, "local changes"
            else:
                ok, message = update.install()
            try:
                self._install_done.emit(ok, message)
            except RuntimeError:
                pass          # tab destroyed while downloading

        threading.Thread(target=work, daemon=True, name="update-install").start()

    def _on_install_done(self, ok: bool, message: str) -> None:
        self._installing = False
        latest = (self._last_check.latest if self._last_check else "").lstrip("v")
        self.update_apply_btn.setEnabled(True)
        self.update_check_btn.setEnabled(True)
        self._log(t("log_update",
                    msg=(message.splitlines()[-1] if message else "ok")))
        if ok:
            QMessageBox.information(self, t("update_done"),
                                    t("update_done_body", latest=latest or "?"))
            self.updateAvailable.emit(False)
        elif message == "local changes":
            QMessageBox.warning(self, t("update_failed"), t("update_dirty"))
        else:
            QMessageBox.critical(self, t("update_failed"), message or "")
        self.check_update()





