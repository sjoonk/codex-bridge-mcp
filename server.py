"""codex-bridge-mcp
Claude Desktop / Cowork에서 로컬 Codex CLI에 작업과 이미지 생성을 위임하는 MCP 서버.
모든 결과는 로컬 작업 폴더(CODEX_BRIDGE_WORKSPACE)에 저장된다.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── 설정 (환경변수로 덮어쓰기) ─────────────────────────────────────────
CODEX_BIN = os.environ.get("CODEX_BIN") or shutil.which("codex") or "codex"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
TIMEOUT = int(os.environ.get("CODEX_TIMEOUT", "1800"))
WORKSPACE = Path(
    os.environ.get("CODEX_BRIDGE_WORKSPACE", "~/codex-bridge-workspace")
).expanduser().resolve()
# 작업 폴더는 항상 허용 (기본 cwd/out_dir이 여기라서)
ALLOWED_ROOTS = list(dict.fromkeys([WORKSPACE] + [
    Path(p).expanduser().resolve()
    for p in os.environ.get("CODEX_BRIDGE_ALLOWED_ROOTS", "").split(os.pathsep)
    if p.strip()
]))
# codex(내장 $imagegen) | gpt-image-2(gpt-image-bridge) | codex-image
IMAGE_BACKEND = os.environ.get("CODEX_BRIDGE_IMAGE_BACKEND", "codex")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

mcp = FastMCP("codex-bridge")


# ── 내부 유틸 ──────────────────────────────────────────────────────────
def _resolve_dir(path: str | None, default: Path) -> Path:
    """경로를 절대경로로 바꾸고 허용 루트 안인지 확인한다."""
    p = (Path(path).expanduser() if path else default).resolve()
    if not any(p == root or root in p.parents for root in ALLOWED_ROOTS):
        raise ValueError(
            f"허용되지 않은 경로: {p}\n"
            f"허용 루트: {[str(r) for r in ALLOWED_ROOTS]} "
            "(CODEX_BRIDGE_ALLOWED_ROOTS에 추가하세요)"
        )
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=TIMEOUT, stdin=subprocess.DEVNULL,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"{TIMEOUT}초 타임아웃"
    except FileNotFoundError:
        return 127, "", f"실행 파일을 찾을 수 없음: {cmd[0]}"


def _codex_exec(prompt: str, cwd: Path, allow_write: bool) -> tuple[int, str, str]:
    """codex exec를 비대화형으로 실행하고 (exit code, 최종 메시지, stderr)를 반환."""
    fd, tmp = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    out = Path(tmp)
    cmd = [
        CODEX_BIN, "exec", "--skip-git-repo-check",
        "--sandbox", "workspace-write" if allow_write else "read-only",
        "--output-last-message", str(out),
        "--", prompt,  # '-'로 시작하는 프롬프트가 옵션으로 해석되지 않게
    ]
    code, _stdout, stderr = _run(cmd, cwd)
    msg = out.read_text(encoding="utf-8").strip() if out.exists() else ""
    out.unlink(missing_ok=True)
    return code, msg, stderr


def _save_handoff(task: str, result: str) -> Path:
    d = WORKSPACE / "handoff"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"codex-{datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(f"# Task\n\n{task}\n\n# Result\n\n{result}\n", encoding="utf-8")
    return path


def _find_new_image(dirs: list[Path], since: float) -> Path | None:
    """since 이후에 생긴 가장 최근 이미지 파일을 찾는다."""
    found: list[Path] = []
    for d in dirs:
        if d.exists():
            found += [
                f for f in d.rglob("*")
                if f.suffix.lower() in IMAGE_EXTS and f.is_file() and f.stat().st_mtime >= since
            ]
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def _threaded(fn):
    """동기 툴을 스레드에서 실행해 장시간 작업 중에도 서버 이벤트 루프가 막히지 않게 한다."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)
    return wrapper


# ── MCP 툴 ────────────────────────────────────────────────────────────
@mcp.tool()
@_threaded
def bridge_status() -> str:
    """브리지 설정과 Codex 설치·로그인 상태를 확인한다. 처음 쓸 때나 오류가 날 때 호출."""
    _, ver, ver_err = _run([CODEX_BIN, "--version"], Path.home())
    _, login, login_err = _run([CODEX_BIN, "login", "status"], Path.home())
    return json.dumps({
        "codex_bin": CODEX_BIN,
        "codex_version": (ver or ver_err).strip(),
        "login_status": (login or login_err).strip(),
        "workspace": str(WORKSPACE),
        "allowed_roots": [str(r) for r in ALLOWED_ROOTS],
        "image_backend": IMAGE_BACKEND,
        "timeout_sec": TIMEOUT,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
@_threaded
def codex_run(prompt: str, cwd: str | None = None, allow_write: bool = False) -> str:
    """Codex(GPT)에게 작업을 맡기고 최종 응답을 받는다.

    prompt: 맥락 없이도 이해되는 자기완결적 지시문.
    cwd: Codex가 작업할 맥(호스트)의 절대경로. 생략하면 작업 폴더. Cowork 샌드박스 경로 금지.
    allow_write: True면 cwd 안의 파일 수정 허용. 기본은 읽기 전용.
    결과 원문은 작업 폴더의 handoff/ 에 저장된다.
    """
    workdir = _resolve_dir(cwd, WORKSPACE)
    code, msg, stderr = _codex_exec(prompt, workdir, allow_write)
    if not msg:
        return f"[실패: exit {code}]\n{stderr[-3000:]}"
    saved = _save_handoff(prompt, msg)
    return f"{msg}\n\n---\n(원문 저장: {saved})"


@mcp.tool()
@_threaded
def codex_image(
    prompt: str,
    filename: str = "image.png",
    out_dir: str | None = None,
    size: str = "1024x1024",
) -> str:
    """ChatGPT 구독(gpt-image-2)으로 이미지를 생성해 로컬에 저장하고 경로를 반환한다.

    prompt: 이미지 설명(구도, 스타일, 텍스트 포함 여부 등 구체적으로).
    filename: 저장 파일명 (예: thumbnail.png).
    out_dir: 저장 폴더(맥 절대경로). 생략하면 작업 폴더의 images/.
    size: 1024x1024 | 1024x1536 | 1536x1024 등.
    한 장에 1~4분 걸린다. 투명 배경은 지원하지 않는다.
    """
    dest_dir = _resolve_dir(out_dir, WORKSPACE / "images")
    dest = dest_dir / Path(filename).name
    if dest.suffix.lower() not in IMAGE_EXTS:
        dest = dest.with_suffix(".png")
    start = time.time() - 1
    log = ""

    if IMAGE_BACKEND == "gpt-image-2":
        code, out, err = _run(["gpt-image-2", "--size", size, "--", prompt, str(dest)], dest_dir)
        log = out + err
    elif IMAGE_BACKEND == "codex-image":
        code, out, err = _run(["codex-image", "generate", prompt, "--out", str(dest_dir)], dest_dir)
        log = out + err
    else:
        instruction = (
            "Use the $imagegen image generation tool to create one image.\n"
            f"Size: {size}\n"
            f"Prompt: {prompt}\n\n"
            f"Save the final image as ./{dest.name} in the current directory. "
            'When done, reply only with JSON: {"path": "<absolute path>"}'
        )
        code, out, err = _codex_exec(instruction, dest_dir, allow_write=True)
        log = out + "\n" + err

    def is_fresh() -> bool:  # 이전 실행에서 남은 같은 이름 파일은 성공으로 치지 않는다
        return dest.exists() and dest.stat().st_mtime >= start

    # 지정 파일명으로 저장되지 않은 경우: 새로 생긴 이미지를 찾아 옮긴다
    if not is_fresh():
        new = _find_new_image([dest_dir, CODEX_HOME], start)
        if new and new != dest:
            shutil.copy2(new, dest)

    if is_fresh():
        return json.dumps(
            {"path": str(dest), "bytes": dest.stat().st_size, "backend": IMAGE_BACKEND},
            ensure_ascii=False,
        )
    return f"[이미지 생성 실패: exit {code}, backend={IMAGE_BACKEND}]\n{log[-3000:]}"


if __name__ == "__main__":
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    mcp.run()
