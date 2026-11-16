# Plot Digitizer

그래프 이미지(논문 figure, TCAD/측정 plot, 스크린샷)에서 데이터 포인트를 추출하는 도구입니다.

- **Web**: https://niceysyu.github.io/plot-digitizer/ — 설치 없이 브라우저에서 실행
- **Desktop**: [Releases](https://github.com/niceysyu/plot-digitizer/releases/latest) — Windows `.exe` / macOS `.app` / Linux binary

## Features

- Axis calibration: 4점 (X1, X2, Y1, Y2), **linear / log scale** 각 축 독립 설정, 약간 회전된 스캔 이미지 대응
- Manual digitizing: 클릭 추가 · 드래그 이동 · 우클릭 삭제 · 확대경(magnifier) · undo
- **Color-based auto extraction**: 곡선 색상 선택 → tolerance / X step 지정 → 자동 추출
- Multiple datasets (series 이름·색상)
- Export: clipboard (Tab → Excel 바로 붙여넣기) / CSV (UTF-8 BOM), 현재 시리즈 · long · wide 형식
- Desktop 전용: 프로젝트 저장/열기 (이미지 + 보정 + 점을 하나의 `.json`에), 이미지를 exe 아이콘에 drag & drop하여 열기

## 사용법

1. 이미지 열기 (Ctrl+O) 또는 붙여넣기 (Ctrl+V)
2. **① Axis 보정**: X축 위 값을 아는 두 점, Y축 위 두 점을 클릭 → 값 입력 (log 축은 체크)
3. **② 점 추가** 또는 **③ Color pick** → `현재 시리즈에 추출`
4. 클립보드 복사 / CSV 저장

| 조작 | 동작 |
|---|---|
| 휠 | 확대/축소 |
| Space+드래그, 휠버튼 드래그 | 화면 이동 |
| `C` / `A` / `P` / `F` | 보정 / 추가 / 색상 / 화면 맞춤 |
| `Backspace` | 마지막 점 삭제 |
| `Ctrl+Z` | 되돌리기 |

## Run from source

```bash
pip install -r desktop/requirements.txt
python desktop/plot_digitizer.py [image.png]
```

Tkinter (Python 기본 포함) + Pillow만 사용합니다.

## Build executable

- Windows: `desktop\build_windows.bat` 실행 → `desktop\dist\PlotDigitizer.exe`
- macOS / Linux: `bash desktop/build.sh`
- 자동 빌드: GitHub에서 Release를 발행(또는 `v*` 태그 push)하면 Actions가 3개 OS용 실행 파일을 빌드해 해당 Release에 첨부합니다.

## Repository layout

```
docs/index.html            # Web app (GitHub Pages)
desktop/plot_digitizer.py  # Desktop app (Python / Tkinter)
.github/workflows/build.yml
```

## License

MIT — see [LICENSE](LICENSE)
