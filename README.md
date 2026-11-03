# 채팅봇

Discord 앱이나 웹을 열지 않고 사용하는 Windows·Android용 봇 채팅 프로그램입니다.
토큰 로그인 → 서버 선택 → 카테고리별 채널 선택 순서로 사용합니다. 모든 대화는 같은 창에서 전환됩니다.
모든 메시지는 **봇 계정**으로 전송됩니다. 개인 계정 및 개인 DM은 지원하지 않습니다.

## Discord 봇 준비

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 애플리케이션을 생성하고 Bot 화면에서 봇 토큰을 발급합니다.
2. Bot → Privileged Gateway Intents → **Message Content Intent**를 켭니다.
3. Installation 또는 OAuth2 URL Generator에서 `bot` 범위로 서버에 초대합니다.
4. 필요한 채널에만 **View Channels / Read Message History / Send Messages** 권한을 부여합니다. 관리자 권한은 필요하지 않습니다.

## 실행

### Android APK 실행

1. [GitHub Releases](https://github.com/Axicavlo/DiscordBotChat/releases)에서 `ChatBot-버전.apk`를 휴대폰에 내려받아 설치합니다.
2. 앱을 열고 봇 토큰을 입력해 연결합니다. 알림 권한을 허용하면 연결 상태와 종료 버튼을 알림에서 확인할 수 있습니다.
3. 서버·채널을 선택하고 메시지를 전송합니다. 메시지를 길게 누르면 답장·사용자 멘션·복사 메뉴가 열립니다.

Android 7.0 이상인 64비트 ARM 휴대폰과 x86_64 에뮬레이터를 대상으로 합니다.
별도 서버 없이 휴대폰이 Discord에 직접 연결합니다. 홈 버튼으로 내려도 연결 서비스를 유지하며,
절전·네트워크 변경으로 연결이 끊기면 재연결합니다. Android가 앱을 강제 종료하거나 사용자가 연결을 종료하면 봇도 오프라인이 됩니다.
앱 복귀 시 선택한 채널의 최근 메시지를 다시 불러옵니다. 24시간 연결 유지는 보장하지 않습니다.

### EXE 실행

1. 빌드된 `ChatBot.exe`를 더블클릭합니다. 이 프로젝트에서 빌드한 파일은 `dist\ChatBot.exe`에 있습니다.
2. 첫 실행 시 봇 토큰을 입력하고 **연결하기**를 누릅니다.
3. 연결 후 서버와 채널을 선택해 대화합니다.

Python 설치나 배치파일 실행은 필요 없습니다. 이미지와 실행 라이브러리가 포함되어 있어 EXE 파일만 옮겨 실행할 수 있습니다.
EXE는 Git에 포함하지 않으므로 소스만 내려받은 경우 아래 **EXE 빌드** 과정을 먼저 진행하세요.

### Python 실행

Python 3.11 이상(Tkinter 포함)이 필요합니다.

1. 최초 한 번 `setup.bat`을 실행해 가상 환경과 discord.py를 설치합니다.
2. `start.bat`을 실행합니다. 별도 콘솔 창 없이 기본 창이 열립니다.
3. 봇 토큰을 입력하고 연결합니다.

### EXE 빌드

Windows에서 Python 3.11 이상(Tkinter 포함)을 설치한 뒤 진행합니다. 최초 환경 구성과 빌드 도구 설치에는 인터넷 연결이 필요합니다.

1. 최초 한 번 `setup.bat`을 실행합니다.
2. `build_exe.bat`을 실행합니다.
3. 빌드 완료 후 `dist\ChatBot.exe`를 실행합니다.

빌드 스크립트는 `requirements-build.txt`에 지정한 PyInstaller를 설치하고 콘솔 창 없는 단일 EXE를 생성합니다.
코드를 수정했다면 EXE를 종료한 뒤 다시 빌드하세요. 토큰 파일은 빌드에 포함하지 않습니다.

### APK 빌드

Windows에서 `setup.bat`으로 Python 환경을 준비한 뒤 `build_apk.bat`을 실행합니다.
최초 실행은 JDK 17·Python 3.12·Gradle·Android SDK와 Python 패키지를 `.build-tools`에 내려받으므로 시간이 걸립니다.
빌드 과정에서 Android SDK 라이선스에 동의합니다. WSL이나 Android Studio 설치는 필요하지 않으며 시스템 기본 Java를 변경하지 않습니다.

완료되면 `dist\ChatBot.apk`와 `dist\ChatBot-버전.apk`가 생성됩니다.
현재 추출 도구는 직접 설치 가능한 디버그 서명 APK를 만듭니다. 업데이트 설치에는 같은 서명 키가 필요하므로
`.build-tools\android-user`의 서명 키를 보관하세요. Google Play 배포용 릴리스 서명은 별도 설정이 필요합니다.

### 공통 기능과 버전 관리

| 파일 | 역할 |
| --- | --- |
| `chatbot_core/__init__.py` | 양쪽 앱이 함께 사용하는 Discord 연결·메시지·답장·재연결 로직 |
| `chatbot_core/version.py` | 공통 버전 `VERSION`과 Android 업데이트 번호 `VERSION_CODE` |
| `app.py` | 기존 Windows Tkinter 화면·Windows 토큰 저장 |
| `android/` | Android 화면·연결 서비스·Android 토큰 저장 |
| `build_exe.bat` | 현재 공통 코드를 포함한 Windows EXE 생성 |
| `build_apk.bat` | 현재 공통 코드를 포함한 Android APK 생성 |

공통 기능을 수정한 뒤 원하는 빌드 도구를 실행하면 해당 플랫폼의 프로그램이 생성됩니다.
배포 시 `VERSION`과 `VERSION_CODE`를 함께 올리고 양쪽을 다시 빌드하세요.
화면·운영체제별 기능은 각각 구현하며, 빌드 도구는 설치된 앱을 자동 업데이트하지 않습니다.

## 사용 방법

- 맨 왼쪽 서버 아이콘을 클릭하고, 카테고리별 채널 목록에서 채널을 선택합니다.
- 같은 창에서 대화를 전환하며 채널별 초안과 답장 대상은 유지됩니다.
- 채널 목록 우상단의 왼쪽 화살표로 목록을 접고, 접힌 위치의 오른쪽 화살표로 펼칩니다.
- 맨 위 홈 아이콘에서 토큰을 변경해 다른 봇으로 연결할 수 있습니다. 봇 변경 시 기존 대화와 초안은 초기화됩니다.
- 메시지는 전송 버튼 또는 Enter로 보냅니다. Shift+Enter 또는 Alt+Enter는 줄바꿈입니다.

## 토큰 저장

연결에 성공한 마지막 토큰은 Windows 사용자 계정으로 암호화해 저장하고 다음 실행 때 자동으로 채웁니다. 연결 시 입력란은 지워집니다.

| 실행 방식 | 저장 위치 |
| --- | --- |
| EXE | `%LOCALAPPDATA%\DiscordChatBot\.bot-token.dat` |
| Python | `app.py`와 같은 폴더의 `.bot-token.dat` |
| Android | 앱 내부 저장소 (Android Keystore의 AES-GCM 키로 암호화) |

실행 방식마다 토큰을 따로 저장하므로 다른 방식으로 전환할 때 토큰을 한 번 입력해야 합니다.
저장 정보를 지우려면 프로그램을 종료한 후 해당 파일을 삭제하세요.
Android는 앱의 **토큰 삭제** 버튼으로 저장 정보를 삭제합니다. 토큰은 연결 성공 후에만 저장합니다.

토큰은 다른 사람에게 공유하거나 채팅에 붙여넣지 마세요. 선택적으로 `DISCORD_BOT_TOKEN` 환경 변수도 사용할 수 있습니다.
프로그램을 종료하면 봇 연결도 종료됩니다. 인터넷 연결은 필요합니다.

## 동작 범위

- 서버 텍스트 채널: 최근 100개, 실시간 수신, 전송, 수정·삭제 반영. 창에는 최근 500개를 유지합니다.
- 첨부파일은 URL로 표시하며 업로드·이미지 미리보기·스레드·포럼·음성 채널은 지원하지 않습니다.
- 사용자 멘션은 알림을 보내며, 답장 알림은 선택할 수 있습니다. 전체·역할 멘션 알림은 비활성화되어 있습니다.
- 채널 권한 변경 후에는 목록 새로고침을 누르세요.
- 네트워크가 복구되면 Discord 연결을 자동 재시도합니다. 맨 왼쪽 서버 목록 하단에 고정된 새로고침 아이콘은 서버·채널 목록과 현재 대화의 최근 기록을 다시 불러옵니다.
- 토큰 및 Intent 오류가 나오면 설정을 수정하고 다시 연결합니다.

문제 확인용 실행: `.venv\Scripts\python.exe app.py`

공식 참고: [discord.py Intents 안내](https://discordpy.readthedocs.io/en/stable/intents.html)
