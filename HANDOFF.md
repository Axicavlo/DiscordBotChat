# 작업 인계 기록

작성일: 2026-11-04 (한국 시간). 다음 세션은 이 문서와 사용자 지침을 먼저 읽고, 실제 Git 상태를 확인한다.

프로젝트 `AGENTS.md`에 매 작업 시작 시 이 문서를 읽고, 완료·중단 전에 갱신하도록 영구 지침을 추가했다. 이 지침 파일과 인계 문서를 텍스트 선택 개선 커밋에 함께 포함한다.

## 현재 상태

### 후속 변경: 텍스트 바깥에서 드래그 시작

- Windows `Chat.start_message_selection`이 글자 위 클릭만 허용하던 조건을 제거했다. 클릭 위치에서 세로 거리가 가장 가까운 메시지를 선택하고, 같은 줄에서는 가로 거리를 비교한다. 빈 좌우 여백이나 위아래에서 시작해도 Canvas 문자 인덱스로 선택을 시작한다.
- 기존처럼 한 메시지 안에서 선택한다. 왼쪽·오른쪽 여백, 본문 위쪽 시작, 메시지 행 구분, 빈 채팅 처리를 실제 Tk Canvas로 확인했다.
- 사용자 요청으로 이 후속 `app.py` 변경과 `AGENTS.md`, `HANDOFF.md`를 함께 커밋하고 `origin/codex/dev`로 푸시한다. 완료 여부와 커밋 SHA는 Git 기록 및 원격 추적 상태로 확인한다. EXE는 `dist/windows-selection/ChatBot.exe`로 빌드하고 기본 `dist/ChatBot.exe`에 반영했으며 파일 해시 일치를 확인했다. 공통 버전은 1.2.6을 유지하며 Android 소스는 변경하지 않았다.

- 프로젝트: Discord 봇 계정으로 메시지를 주고받는 Windows·Android 앱. 별도 중계 서버 없이 Discord에 직접 연결한다.
- 경로: `C:\Users\itcon\Documents\ChatGPT\봇`
- 저장소: https://github.com/Axicavlo/DiscordBotChat
- 브랜치: `codex/dev`
- 최신 기능 커밋: `68a930d` — `feat: refine chat input and server display names` (푸시 완료).
- 버전: `1.2.6`, Android `VERSION_CODE = 10206`.
- APK 릴리즈: https://github.com/Axicavlo/DiscordBotChat/releases/tag/v1.2.6
- APK 다운로드: https://github.com/Axicavlo/DiscordBotChat/releases/download/v1.2.6/ChatBot-1.2.6.apk
- 문서 작성 전 작업 트리는 기존 미추적 파일 `intent-confirmation.png`, `intent-enabled.png`만 있었다. 삭제하거나 무관한 커밋에 포함하지 않는다.
- 현재 새 기능 요청은 없다. 마지막 기능 요청인 서버 닉네임 표시는 구현·빌드·커밋·푸시·APK 릴리즈까지 완료했다. 이 인계 문서는 후속 텍스트 선택 개선과 함께 버전 관리한다.

## 사용자 작업 방식

- 사용자가 제공한 AGENTS.md 지침을 따른다. 명확한 수정 요청과 허가 없이 코드를 바꾸지 않는다. 이번 요청은 인계 문서 작성이다.
- 저장소 구조 파악·코드 위치 확인은 먼저 `graft map`, `graft ask "질문" --source`, `graft skeleton`, `graft callers` 등을 사용한다. 큰 코드 변경 뒤 `graft build`로 갱신한다.
- 사용자 승인 없이 별도 에이전트를 생성하지 않는다.
- 한국어로 간결하게 설명한다. 문제가 없으면 테스트를 불필요하게 반복하지 말라는 사용자 선호가 있다.
- 이전 작업에서 완료 후 APK를 GitHub Release에 올리도록 요청했다. 후속 변경의 배포 범위는 최신 요청을 함께 확인한다.
- 토큰·인증정보는 문서, 로그, 커밋, APK에 넣지 않는다. 사용자 실행 중인 앱을 임의로 종료하지 않는다.

## 파일 구조

| 경로 | 역할 |
| --- | --- |
| `chatbot_core/__init__.py` | 공통 Discord 연결·메시지·답장·재연결·서버 닉네임 처리 |
| `chatbot_core/version.py` | 공통 버전과 Android 업데이트 번호 |
| `app.py` | Windows Tkinter UI |
| `windows_ime.py` | Tk 이벤트 루프에서 한글 조합 문자열 표시 |
| `native/ime_preview.c` | Python/Tk를 호출하지 않는 네이티브 IME 메시지 처리 |
| `tools/build_ime.py` | Visual Studio C++ 도구로 IME DLL 생성 |
| `android/app/src/main/java/com/axicavlo/chatbot/MainActivity.java` | Android 네이티브 화면 |
| 같은 Java 디렉터리의 `BotService.java` | Discord 연결을 유지하는 foreground service |
| 같은 Java 디렉터리의 `TokenStore.java` | Android Keystore 기반 토큰 암호화 저장 |
| `android/app/src/main/python/mobile_client.py` | 공통 Bridge를 Android JSON 상태로 변환 |
| `tools/build_android.py` | Windows에서 Android 도구 준비 및 APK 빌드 |

## 완료한 UI·동작

- 두 플랫폼 모두 별도 @ 버튼을 제거했다. 입력창에 `@`를 입력하면 채팅 영역 안에 테마에 맞는 사용자 목록 오버레이가 열린다. 외부 창을 띄우거나 채팅 영역 높이를 줄이지 않는다.
- 답장은 항상 알림을 요청한다. 알림 체크박스와 설명 텍스트는 제거했다.
- 답장 표시 영역은 답장 중에만 보이고, 취소 버튼은 작은 투명 배경 `×`이다.
- Android: 왼쪽 서버 목록은 유지하고 오른쪽에 채널 목록 또는 채팅을 표시한다. 홈은 토큰 페이지로 이동한다. 서버 선택 시 채널 목록, 채팅에서 뒤로가기는 채널 목록으로 이동한다. Windows의 목록 접기 화살표는 없다. 홈·새로고침 버튼 배경은 투명하다.
- Windows: 메시지 호버 효과를 제거하고 우클릭 메뉴를 앱 테마에 맞는 내부 UI로 바꿨다.
- Windows: 메시지 본문을 드래그해 일부를 선택하고 Ctrl+C 또는 우클릭의 선택 영역 복사로 복사할 수 있다. 현재 선택 범위는 한 메시지 내부이며 여러 말풍선을 가로지르는 선택은 구현하지 않았다. 한글·이모지 인덱스는 Tcl 문자열 기준으로 처리한다.
- 두 플랫폼: 작성자·답장·멘션 후보는 서버 닉네임을 우선 표시한다. 닉네임을 얻지 못하면 Discord 표시 이름 등으로 대체한다. 실제 멘션 전송은 ID를 사용한다.

## 서버 닉네임 구현

- 공통 `server_display_name`과 `Bridge.member_names`를 사용한다. 캐시 키는 서버 ID와 사용자 ID 조합이다.
- 메시지 작성자·멘션 대상·해석된 답장 대상의 Member 정보를 준비한 뒤 화면에 보낸다. 필요하면 `guild.fetch_member`로 조회한다.
- 캐시 유효기간 300초, 실패 재시도 간격 30초, 동시 조회 4개, 전체 대기 제한 8초이다. 조회 실패 때문에 채팅을 중단하지 않는다.
- 최신 gateway Member 정보를 우선하며, 별도 privileged Members Intent는 추가하지 않았다.
- 메시지 본문 안의 멘션 문자열 변환은 기존 Discord `clean_content` 동작을 유지한다. 이번 변경 대상은 작성자·답장·후보 목록이다.
- 서버별 이름 분리, 캐시 재사용·갱신, 조회 실패 시 대체 표시를 모의 객체로 확인했다. 실제 사용자 환경에서 닉네임 변경 즉시 갱신까지 보장하는 별도 검증은 하지 않았다.

## 한글 입력 강제 종료와 조합 문자열 표시

- 사용자 보고: Windows에서 한글 입력 시 종료, 영문은 정상. 이벤트 로그에 `ucrtbase.dll`, 예외 `0xc0000409`가 확인됐다. 실제 충돌 스택은 확보하지 못했다.
- 과거 Python ctypes Windows 콜백이 Tk를 직접 호출하던 구조를 제거했다. 이 구조를 다시 도입하지 않는다.
- 현재 C DLL은 Windows 콜백 안에서 조합 문자열을 저장하고 완료 문자열 처리를 기본 경로로 전달한다. Python/Tk 호출은 하지 않는다.
- `windows_ime.py`가 Tk `after(15)`로 읽고, 입력창과 같은 폰트·색·Text 렌더러를 쓰는 자식 Text에 조합 중 글자를 밑줄로 표시한다. 확정된 입력창 본문은 수정하지 않는다.
- 위치는 양쪽 `dlineinfo`의 기준선으로 맞춘다. `place(..., bordermode='outside')`는 부모 패딩이 이중 적용되는 문제를 막으므로 유지한다.
- 네이티브 메시지 모의 반복 1,000회와 폰트·기준선·위치·종료 처리를 확인했다. 실제 사용자 키보드/IME 조합의 완전한 재현 검증으로 표현하면 안 된다.
- DLL 없는 소스 실행은 Tk 기본 IME로 대체된다. EXE에는 DLL을 포함해야 한다.

## 빌드 및 결과물

Windows PowerShell, 프로젝트 루트 기준:

```powershell
# 최초 환경 구성
.\setup.bat

# Windows EXE: Visual Studio C++ x64 빌드 도구와 Windows SDK 필요
.\build_exe.bat

# Android APK
.\build_apk.bat
```

- Windows 기본 실행 파일: `dist\ChatBot.exe` (현재 1.2.6).
- 보관 빌드: `dist\windows-1.2.6\ChatBot.exe`.
- Android: `dist\ChatBot.apk`, `dist\ChatBot-1.2.6.apk`.
- `build_exe.bat`은 IME DLL을 빌드하고 PyInstaller 단일 windowed EXE에 assets와 DLL을 포함한다.
- 버전별 경로로 따로 빌드한다면 다음 명령을 쓸 수 있다. C 소스를 바꿨다면 먼저 `tools\build_ime.py`를 실행한다.

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name ChatBot --distpath "dist/windows-1.2.6" --add-data "assets;assets" --add-binary "native/ime_preview.dll;native" app.py
```

- 사용자는 `dist\ChatBot.exe`를 직접 실행한다. 버전별 폴더만 갱신하고 기본 EXE를 예전 상태로 남기면 안 된다.
- 실행 중 기본 EXE 덮어쓰기가 실패하면 사용자 앱을 강제 종료하지 않는다. 기존 EXE 단일 파일을 워크스페이스의 `.build-tools` 아래 고유 백업명으로 이동하고 새 EXE를 복사하는 방법을 사용했다. 실패하면 원복하고 성공하면 파일 해시를 비교한다. 실제 열린 창은 이전 코드이므로 닫고 다시 실행해야 한다.
- Android 빌드는 `.build-tools`에 JDK17, Python3.12.10 NuGet 배포판, Gradle8.9, Android cmdline-tools19.0/SDK35 등을 준비한다. Python embedded 배포판은 venv 문제 때문에 사용하지 않는다.
- Android는 Chaquopy17.2, AGP8.7.3, minSDK24, target/compileSDK35, arm64-v8a 및 x86_64 대상이다.
- APK는 디버그 서명이다. 업데이트 설치를 위해 `.build-tools\android-user`의 서명 키를 보존한다. 빌드 캐시를 통째로 삭제하지 않는다.
- 공통 변경 배포 시 `VERSION`, `VERSION_CODE`를 올리고 두 플랫폼을 빌드한다. 앱 자동 업데이트 기능은 없다.

## 검증·미리보기 참고

- 최신 1.2.6 EXE/APK 빌드는 성공했다. 실제 휴대폰 설치 및 Discord 전체 흐름은 이 세션에서 검증하지 않았다.
- `.build-tools`의 임시 검사 파일은 Git에 포함하지 않은 작업 보조물이다: `check_server_names.py`, `check_ime_preview.py`, `native_ime_test.c`, `repro_input.py` 등.
- 오래된 `check_mentions.py`, `check_chat_selection.py`는 최신 메서드 인자·fixture에 맞게 수정해야 재실행할 수 있다. 테스트 실패를 바로 제품 결함으로 단정하지 않는다.
- Android 에뮬레이터는 이 환경에서 부팅하지 못했다. 반복 시도하지 않는다.
- 이전 미리보기는 `.build-tools\native-preview`의 Robolectric 네이티브 그래픽으로 실제 MainActivity 소스를 예시 데이터와 함께 렌더링했다. 실제 설치 APK 화면 캡처가 아니며 시스템 키보드는 제외했다.
- `dist\preview`의 PNG는 과거 UI 상태일 수 있다. 최신 버전 캡처로 제시하기 전에 다시 생성한다.
- 한글 경로 때문에 Java 검사 실행 시 ASCII junction `%TEMP%\chatbot-android-preview` → `.build-tools`를 사용했다. 해당 폴더에 JDK/Gradle 캐시와 native-preview 프로젝트가 연결된다.

## 커밋·릴리즈 참고

- GitHub 플러그인에 필요한 릴리즈 업로드 기능이 없어 GitHub REST API를 사용했다. 저장소는 인증 없이 API 조회하면 404가 나올 수 있다.
- `.build-tools\publish_release.py`는 1.2.6용 임시 도구이다. 재사용 시 태그·파일·노트 경로·제목을 검토한다. 현재 공개 릴리즈를 덮어쓰지 않도록 되어 있다.
- 인증은 Git credential helper에서 메모리로만 읽어 API에 전달한다. 자격증명 출력이나 파일 저장을 하지 않는다.
- 소스 커밋 SHA로 draft 생성 → APK 업로드·크기 확인 → 공개 → 태그 API로 최종 다운로드 URL 확인 순서로 진행했다.
- `.git` 변경·네트워크 접근은 실행 환경에 따라 권한 상승이 필요할 수 있다. 자동 승인 거부 시 거부된 동작과 이유를 사용자에게 명확히 설명한다.

## 다음 세션 시작

1. 이 문서와 적용되는 AGENTS.md를 읽는다.
2. `git status --short`, 현재 브랜치·최신 커밋을 확인한다. 위 기록보다 실제 상태가 우선이다.
3. 사용자의 새 요청을 확인하고 graft로 관련 위치를 찾는다.
4. 이미 완료된 빌드·검증을 이유 없이 반복하지 않는다. 수정 시 필요한 범위만 확인한다.
