"""Typing "->" turns into "→", the way Notion does it.

Driven with real key events rather than by calling a helper, because the
whole point is the behaviour on the keystroke that completes the sequence --
the cursor has to land in the right place, a real "->" has to stay reachable,
and text that was pasted or loaded must never be rewritten.

Run:  .venv\\Scripts\\python.exe tests\\test_arrows.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QEvent, Qt          # noqa: E402
from PySide6.QtGui import QKeyEvent            # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

app = QApplication.instance() or QApplication([])

from app.ui.common import ArrowTextEdit, Field, editor_value, make_editor  # noqa: E402

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def press(widget, ch: str) -> None:
    key = {"-": Qt.Key_Minus, ">": Qt.Key_Greater, " ": Qt.Key_Space,
           "\b": Qt.Key_Backspace}.get(ch, Qt.Key_unknown)
    text = "" if ch == "\b" else ch
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(kind, key, Qt.NoModifier, text))


def typed(widget, s: str) -> None:
    for ch in s:
        press(widget, ch)


def fresh() -> ArrowTextEdit:
    w = ArrowTextEdit()
    w.setFocus()
    return w


def main() -> int:
    print("[기본 변환]")
    w = fresh()
    typed(w, "->")
    check("'->' 가 '→' 로 바뀐다", w.toPlainText() == "→", repr(w.toPlainText()))

    w = fresh()
    typed(w, "A->B")
    check("단어 사이에서도 바뀐다", w.toPlainText() == "A→B", repr(w.toPlainText()))

    w = fresh()
    typed(w, "if x -> y then")
    check("문장 안에서 바뀐다", w.toPlainText() == "if x → y then",
          repr(w.toPlainText()))

    w = fresh()
    typed(w, "a->b->c")
    check("여러 번 바뀐다", w.toPlainText() == "a→b→c", repr(w.toPlainText()))

    print("\n[바뀌지 않아야 하는 경우]")
    w = fresh()
    typed(w, "- ")
    check("'-' 다음 공백은 그대로", w.toPlainText() == "- ", repr(w.toPlainText()))

    w = fresh()
    typed(w, "5 > 3")
    check("앞에 '-' 없는 '>' 는 그대로", w.toPlainText() == "5 > 3",
          repr(w.toPlainText()))

    w = fresh()
    w.setPlainText("already has -> in it")   # loaded/pasted, not typed
    check("불러온 텍스트의 '->' 는 안 건드린다",
          w.toPlainText() == "already has -> in it", repr(w.toPlainText()))

    print("\n[되돌리기]")
    w = fresh()
    typed(w, "->")
    press(w, "\b")
    check("변환 직후 Backspace 로 '->' 복원", w.toPlainText() == "->",
          repr(w.toPlainText()))

    w = fresh()
    typed(w, "->")
    typed(w, "x")            # a keystroke after conversion cancels the revert
    press(w, "\b")
    check("다른 키를 친 뒤 Backspace 는 보통 삭제", w.toPlainText() == "→",
          repr(w.toPlainText()))

    print("\n[적용 범위: 내용 칸만]")
    content = make_editor(Field("english", "f_english", "text", 66))
    typed_source = make_editor(Field("source", "f_source", "line", 0))
    check("내용 칸(text)은 ArrowTextEdit", isinstance(content, ArrowTextEdit))
    check("출처 칸(line)은 일반 입력칸",
          not isinstance(typed_source, ArrowTextEdit),
          type(typed_source).__name__)

    print("\n[커서가 화살표 바로 뒤]")
    w = fresh()
    typed(w, "a->")
    typed(w, "b")
    check("변환 뒤 이어 입력하면 화살표 다음에 붙는다",
          w.toPlainText() == "a→b", repr(w.toPlainText()))

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 화살표 변환 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
