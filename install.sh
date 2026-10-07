#!/usr/bin/env bash
# codex-bridge-mcp 설치: 가상환경 생성 → 의존성 설치 → Claude Desktop 설정 스니펫 출력
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
WORKSPACE="${1:-$HOME/codex-bridge-workspace}"

command -v python3 >/dev/null || { echo "python3가 필요합니다."; exit 1; }
CODEX_BIN="$(command -v codex || true)"
[ -n "$CODEX_BIN" ] || echo "⚠️  codex를 찾지 못했습니다. 'brew install codex' 후 'codex login'을 먼저 하세요."

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "mcp>=1.2.0,<2"
mkdir -p "$WORKSPACE"/{handoff,images}

cat << JSON

✅ 설치 완료. 아래를 Claude Desktop 설정 파일의 "mcpServers" 안에 추가하세요:
   ~/Library/Application Support/Claude/claude_desktop_config.json

    "codex-bridge": {
      "command": "$PROJECT_DIR/.venv/bin/python",
      "args": ["$PROJECT_DIR/server.py"],
      "env": {
        "CODEX_BIN": "${CODEX_BIN:-/opt/homebrew/bin/codex}",
        "CODEX_BRIDGE_WORKSPACE": "$WORKSPACE",
        "CODEX_BRIDGE_ALLOWED_ROOTS": "$WORKSPACE",
        "CODEX_BRIDGE_IMAGE_BACKEND": "codex"
      }
    }

그다음 Claude Desktop을 완전히 종료(⌘Q) 후 재시작하고,
Cowork에서 작업 폴더로 $WORKSPACE 를 선택하세요.
JSON
