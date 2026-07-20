"""Engo.bat has to survive cmd.exe, which is fussier than it looks.

The v1.0.3 release shipped a batch file with LF-only line endings and Korean
comments in UTF-8. cmd.exe reads batch files in the machine's OEM codepage and
seeks by byte offset through parenthesised blocks, so it lost its place and
started executing fragments of words -- "atever" from "whatever", "ndard" from
"standard" -- and the program would not start at all.

None of that is visible by reading the file. It is visible in the bytes, and
in what `git archive` puts in the release zip, which is what people actually
download. Both are checked here.

Run:  .venv\\Scripts\\python.exe tests\\test_launcher.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok   {label}{('  ' + detail) if detail else ''}")
    else:
        print(f"  FAIL {label}  {detail}")
        _failures.append(label)


def inspect(data: bytes, where: str) -> None:
    crlf = data.count(b"\r\n")
    lone_lf = data.count(b"\n") - crlf
    non_ascii = [b for b in data if b > 127]

    check(f"{where}: 줄 끝이 모두 CRLF", crlf > 0 and lone_lf == 0,
          f"(CRLF {crlf}, LF 단독 {lone_lf})")
    check(f"{where}: 순수 ASCII", not non_ascii,
          f"(비ASCII {len(non_ascii)}바이트)")

    text = data.decode("ascii", errors="replace")
    # A multi-line ( ) block is what cmd mis-seeks through. Single-line uses
    # like `for %%I in (x) do ...` are fine; a trailing ( that opens a block
    # spanning lines is not.
    blocks = [line for line in text.splitlines()
              if line.rstrip().endswith("(") and not line.strip().startswith("rem")]
    check(f"{where}: 여러 줄 ( ) 블록 없음", not blocks,
          f"({len(blocks)}개: {blocks[:2]})")

    # `if cond set A & set B` runs the second command unconditionally, so a
    # flag meant for one interpreter leaks to whichever is found later.
    leaky = [line for line in text.splitlines()
             if re.match(r"\s*if\b", line) and "&" in line]
    check(f"{where}: 조건문에 & 이어붙이기 없음", not leaky,
          f"({leaky[:1]})")


def main() -> int:
    bat = ROOT / "Engo.bat"
    if not bat.exists():
        print("  FAIL Engo.bat 이 없습니다")
        return 1

    print("[작업 폴더의 Engo.bat]")
    inspect(bat.read_bytes(), "작업본")

    print("\n[릴리스 zip 에 들어갈 Engo.bat]")
    # The updater downloads the tag's archive, so this is the copy that runs
    # on other people's machines. .gitattributes is what makes it CRLF.
    if not (ROOT / ".git").exists():
        print("  건너뜀: git 체크아웃이 아닙니다")
    else:
        tree = subprocess.run(["git", "write-tree"], cwd=ROOT,
                              capture_output=True, text=True)
        if tree.returncode:
            print(f"  건너뜀: git write-tree 실패 ({tree.stderr.strip()})")
        else:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "archive.zip"
                made = subprocess.run(
                    ["git", "archive", "--format=zip", tree.stdout.strip(),
                     "-o", str(out)], cwd=ROOT, capture_output=True, text=True)
                if made.returncode:
                    check("git archive 가 성공한다", False, made.stderr.strip())
                else:
                    with zipfile.ZipFile(out) as archive:
                        name = next(n for n in archive.namelist()
                                    if n.endswith("Engo.bat"))
                        inspect(archive.read(name), "릴리스본")

    print("\n[.gitattributes]")
    attrs = ROOT / ".gitattributes"
    check("파일이 있다", attrs.exists())
    if attrs.exists():
        text = attrs.read_text(encoding="utf-8-sig")
        check("*.bat 을 CRLF 로 고정한다",
              re.search(r"\*\.bat\s+.*eol=crlf", text) is not None)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("모든 실행기 테스트 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
