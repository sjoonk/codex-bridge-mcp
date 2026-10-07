# codex-bridge-mcp

Claude Desktop / Cowork에서 **로컬 Codex CLI**에게 작업과 ChatGPT 이미지(gpt-image-2) 생성을 맡기고 결과를 받는 MCP 서버입니다. `codex mcp-server`가 제거된 이후를 위해 `codex exec`(비대화형 모드)를 감싸는 방식으로 동작합니다.

## 구조

```
codex-bridge-mcp/
├── server.py                          # MCP 서버 (툴 3개)
├── pyproject.toml
├── install.sh                         # venv 생성 + 설정 스니펫 출력
├── claude_desktop_config.example.json
└── skills/codex-delegate/SKILL.md     # Cowork용 사용 지침 스킬
```

모든 결과는 로컬 작업 폴더(기본 `~/codex-bridge-workspace`)에 남습니다.

```
~/codex-bridge-workspace/
├── handoff/   # codex_run 결과 원문 (codex-YYYYMMDD-HHMMSS.md)
└── images/    # codex_image 생성 이미지
```

## 툴

| 툴 | 하는 일 |
|---|---|
| `bridge_status` | Codex 경로·버전·로그인 상태, 작업 폴더 확인 |
| `codex_run` | Codex에 작업 위임 후 최종 응답 반환 (기본 읽기 전용) |
| `codex_image` | gpt-image-2로 이미지 생성 후 로컬 경로 반환 |

## 설치

사전 준비: macOS, Python 3.10+, Codex CLI 설치 및 로그인

```bash
brew install codex
codex login
```

설치:

```bash
cd codex-bridge-mcp
./install.sh                        # 작업 폴더 기본값: ~/codex-bridge-workspace
./install.sh ~/YOUR/assets    # 작업 폴더를 직접 지정할 수도 있음
```

출력된 JSON 스니펫을 `~/Library/Application Support/Claude/claude_desktop_config.json`의 `mcpServers`에 넣고 Claude Desktop을 완전히 종료(⌘Q) 후 재시작합니다. Cowork 세션의 작업 폴더로 같은 작업 폴더를 선택해야 Cowork가 결과 파일을 바로 볼 수 있습니다.

스킬 등록:

```bash
cd skills && zip -r codex-delegate.zip codex-delegate
```

만든 zip을 Claude 설정의 Skills에서 업로드합니다.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `CODEX_BIN` | PATH의 `codex` | Desktop은 PATH가 짧으니 절대경로 권장 |
| `CODEX_BRIDGE_WORKSPACE` | `~/codex-bridge-workspace` | 결과 저장 폴더 |
| `CODEX_BRIDGE_ALLOWED_ROOTS` | 작업 폴더 | Codex가 접근할 수 있는 루트 (`:`로 여러 개) |
| `CODEX_BRIDGE_IMAGE_BACKEND` | `codex` | `codex`(내장 $imagegen) / `gpt-image-2` / `codex-image` |
| `CODEX_TIMEOUT` | `1800` | 호출당 타임아웃(초) |

`codex_run`의 `cwd`와 `codex_image`의 `out_dir`는 허용 루트 밖이면 거부됩니다. 다른 프로젝트 폴더도 쓰려면 `CODEX_BRIDGE_ALLOWED_ROOTS`에 추가하세요.

## 이미지가 저장되지 않을 때

Codex 버전에 따라 `$imagegen` 결과가 지정 파일명으로 저장되지 않을 수 있습니다. 서버는 작업 폴더와 `~/.codex`에서 호출 이후 생긴 이미지를 찾아 복사하는 폴백을 갖고 있지만, 그래도 실패하면 백엔드를 래퍼로 바꾸세요.

- [gpt-image-bridge](https://github.com/oakplank/gpt-image-bridge) 설치 후 `gpt-image-2`가 PATH에 있으면 → `CODEX_BRIDGE_IMAGE_BACKEND=gpt-image-2`
- [codex-image](https://github.com/tksuns12/codex-image) 설치 후 → `CODEX_BRIDGE_IMAGE_BACKEND=codex-image`

Desktop에서 실행될 때 PATH가 짧아 래퍼를 못 찾으면, 래퍼를 `/usr/local/bin`이나 `/opt/homebrew/bin`에 링크하세요.

## 문제 해결

- 툴이 Cowork에 안 보임 → 설정 JSON 문법 확인, Desktop 완전 재시작, `~/Library/Logs/Claude/mcp-server-codex-bridge.log` 확인
- `실행 파일을 찾을 수 없음` → `CODEX_BIN`에 `which codex` 결과를 절대경로로 지정
- 로그인 오류 → 터미널에서 `codex login status` 확인 후 `codex login`
- 플래그 오류 → `codex exec --help`로 현재 버전의 옵션명 확인 후 `server.py`의 `_codex_exec` 수정

## 참고

- 이미지 생성은 텍스트보다 Codex 사용 한도를 훨씬 빨리 소모합니다.
- gpt-image-2는 투명 배경 PNG를 지원하지 않습니다.
- `codex_run`은 매 호출이 새 세션입니다. 이어서 묻으려면 이전 결과를 지시문에 포함하세요.
