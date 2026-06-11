# K-LightShow USB Automator

K-Lightshow 공연용 USB에 쇼 파일(.mp3, .fseq)을 좌표별로 자동 복사해주는 데스크톱 프로그램입니다. Windows와 macOS를 모두 지원합니다.

A desktop tool that automates copying K-Lightshow show files (.mp3, .fseq) onto USB drives by seat coordinate. Supports both Windows and macOS.

## 관련 링크

- K-LightShow 공식 홈페이지: <https://www.k-lightshow.com/>
- K-LightShow 쇼 파일 제작 사이트: <https://klightshow.pages.dev/>

## 주요 기능

- **좌표 기반 복사**: A04~J63 좌표 버튼 그리드 또는 키보드 입력(`a4`, `A04` 등)으로 대상 좌표 선택
- **자동 파일 복사**: 소스 폴더 루트의 `.mp3` 파일과 좌표 폴더 안의 `.fseq` 파일을 USB의 `Lightshow` 폴더로 복사
- **파일명에 좌표 추가 옵션**: 복사 시 파일 이름 뒤에 좌표를 붙일 수 있음 (예: `BTS_A04.mp3`)
- **USB 볼륨 이름 자동 변경**: USB 드라이브 이름을 좌표명으로 자동 변경
- **자동 안전 제거**: 복사 완료 후 USB를 자동으로 안전하게 제거
- **다중 PC 동기화**: 여러 PC가 **같은 와이파이(네트워크)에 연결되어 있으면** 진행 상황이 자동으로 공유됩니다. 한 PC에서 좌표 복사가 완료되면 UDP 브로드캐스트(포트 45454)로 알려서, 다른 PC에서도 해당 좌표가 초록색(동기화됨)으로 표시됩니다. 별도 설정 없이 동작하며, Windows와 macOS 간에도 공유됩니다.
- **진행 상태 표시**: 좌표별 상태를 색상으로 표시 (흰색: 대기, 노란색: 진행 중, 초록색: 완료, 빨간색: 실패)

## 다운로드

[Releases](https://github.com/jangcuber/K-LightShow-USB-Automator/releases) 페이지에서 빌드된 프로그램을 받을 수 있습니다.

- **Windows**: `K-LightShow_USB_Manager.exe`
- **macOS**: `K-LightShow_USB_Manager_Mac.zip` (압축 해제 후 `.app` 실행, Apple Silicon 기준)

> macOS에서 "확인되지 않은 개발자" 경고가 뜨면, 앱을 우클릭 → 열기로 실행하세요.

## 소스 폴더 구조

소스 폴더는 아래와 같은 구조를 가정합니다:

```
소스 폴더/
├── 곡이름1.mp3          # 루트의 mp3는 모든 좌표에 복사됨
├── 곡이름2.mp3
├── A04/
│   └── show.fseq        # 각 좌표 폴더의 fseq는 해당 좌표에만 복사됨
├── A05/
│   └── show.fseq
└── ...
```

복사 결과 (USB):

```
USB (볼륨명: A04)/
└── Lightshow/
    ├── 곡이름1_A04.mp3
    ├── 곡이름2_A04.mp3
    └── show_A04.fseq
```

## 사용 방법

1. 프로그램 실행
2. **소스 폴더 선택** 버튼으로 mp3와 좌표 폴더가 들어 있는 폴더 선택
3. USB를 꽂고 **새로고침** 후 드라이브 선택
4. 좌표 버튼 클릭 또는 입력창에 좌표 입력 후 엔터
5. 완료 메시지가 뜨면 USB 제거 후 다음 USB 진행

## 실행 (소스에서)

```bash
pip install -r requirements.txt

# Windows
python usb_manager_windows.py

# macOS
python usb_manager_mac.py
```

## 빌드 (PyInstaller)

```bash
pip install pyinstaller

# Windows (.exe)
pyinstaller K-LightShow_USB_Manager.spec

# macOS
pyinstaller --windowed --onefile --name K-LightShow_USB_Manager_Mac usb_manager_mac.py
```

빌드 결과물은 `dist/` 폴더에 생성됩니다.

## 플랫폼별 차이

| | Windows (`usb_manager_windows.py`) | macOS (`usb_manager_mac.py`) |
|---|---|---|
| USB 감지 | 이동식 디스크 드라이브 문자 (D:~Z:) | `/Volumes/` 마운트 볼륨 |
| 볼륨 이름 변경 | `SetVolumeLabelW` (Win32 API) | `diskutil rename` (실패 시 `fatlabel`/`exfatlabel` 폴백) |
| 안전 제거 | Shell.Application Eject | `diskutil eject` |
