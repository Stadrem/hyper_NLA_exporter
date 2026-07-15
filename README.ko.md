🌐 [English](README.md) | 🇰🇷 [한국어](README.ko.md)

# 🎬 Hyper NLA Exporter 사용자 가이드

블렌더(Blender)를 위한 전문적이고 비파괴적인 애니메이션 워크플로우 생산성 애드온입니다. 타임라인 상의 **마커(Marker)**를 기준으로 하나의 긴 통합 애니메이션을 여러 개의 독립된 클립(Take/Clip)으로 손쉽게 분할하여 FBX 또는 GLB 파일로 단 한 번의 클릭에 내보냅니다. 번거로운 NLA 트랙 수동 생성 과정을 완벽히 생략할 수 있습니다.

> [!IMPORTANT]
> **사용 목적 및 지원 범위**: 이 애드온은 **Unity 게임 엔진용 FBX Animation Take** 추출 및 **웹 기반 서비스용 GLB NLA 애니메이션** 추출을 위해 특화되어 제작되었습니다. 명시된 목적 외의 다른 용도나 환경에서의 정상적인 작동은 보장하지 않습니다.

<p align="center">
  <img src="https://img.shields.io/badge/Blender-5.1+-306EE8?logo=blender&logoColor=white&style=for-the-badge" alt="Blender Version">
  <img src="https://img.shields.io/badge/Format-FBX%20%2F%20GLB-E04E39?style=for-the-badge" alt="Format support">
  <img src="https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge" alt="License">
</p>

---

## 🌟 주요 기능 (Key Features)

* ⚡ **마커 기반 자동 분할**: 타임라인에 심어둔 마커의 이름과 위치를 이용해 각 애니메이션 클립의 이름과 구간을 자동으로 파싱합니다.
* 🚀 **원클릭 퀵 익스포트**: 마커 구간별 액션 분할, 프레임 1번부터 시작하도록 자동 리타이밍, 파일 내보내기, 임시 NLA 정리 작업을 단 한 번의 클릭으로 일괄 수행합니다.
* 💾 **Auto Export (자동 저장)**: 파일 브라우저를 열지 않고, 지정한 위치에 예측 가능한 이름으로 FBX 또는 GLB를 바로 저장하고 덮어쓸 수 있습니다.
* 🔄 **비파괴 워크플로우**: 작업공간의 활성 액션과 NLA 상태를 전혀 훼손하지 않습니다. 모든 분할 작업 및 NLA 변환은 렌더링 순간에만 임시 메모리 내에서 수행됩니다.
* 📐 **경계 키프레임 자동 삽입**: 분할된 각 세그먼트의 첫 프레임과 끝 프레임 위치에 원본 커브 값을 평가해 키프레임을 자동으로 채워주어, 분할 후 포즈가 비틀어지는 포즈 드리프트 현상을 예방합니다.
* ✅ **내보내기 사전 검사**: 중복/빈 클립 이름, 잘못된 마커, 누락된 Action Slot과 F-Curve, 기존 NLA 트랙, 범위 안의 키 유무, 선택에서 빠진 스킨드 메시를 내보내기 전에 확인합니다.
* 📂 **완료 폴더 열기**: 내보내기에 성공하면 생성된 FBX/GLB가 있는 폴더를 자동으로 엽니다.
* ⚙️ **수동 NLA 제어 도구**: 마커를 이용해 영구적인 NLA 트랙을 생성하거나, 분할된 NLA들을 다시 하나의 긴 통합 액션으로 합치고, 깔끔하게 정리하는 복구용 도구를 제공합니다.

---

## 🛠️ 패널 인터페이스 개요 (Panel Interface Overview)

3D Viewport > Sidebar (N-패널) > **K-Quick Tools** 탭의 **Hyper NLA Exporter** 패널에 위치해 있습니다.

```
┌──────────────────────────────────────────┐
│ ▼ 🎬 Hyper NLA Exporter                  │
├──────────────────────────────────────────┤
│ ┌─ Marker Segments ──────────────────┐   │
│ │ 👁 [▶] [ Walk       ] 1~60 (60f) 🗑 │   │
│ │ 👁 [▶] [ Run        ] 61~120(60f) 🗑 │   │
│ │ [Reset Range]                      │   │
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Targets: 1 Objects ───────────────┐   │
│ │  Active Action: Rig_Action         │   │
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Settings ─────────────────────────┐   │
│ │ [ ] Only Deform Bones              │   │
│ │ [x] Create Boundary Keys           │   │
│ │ [x] Selected Only                  │   │
│ │ [x] Open Folder After Export       │   │
│ └────────────────────────────────────┘   │
│                                          │
│ ┌─ Quick Export (Marker Split) ──────┐   │
│ │    [Check FBX]      [Check GLB]     │   │
│ │      [   FBX   ]      [   GLB   ]      │   │
│ └────────────────────────────────────┘   │
│                                          │
│ [▶ Manual NLA Tools]                     │
└──────────────────────────────────────────┘
```

* **Marker Segments**: 타임라인 마커를 기반으로 감지된 애니메이션 클립들을 표시하며, 인라인 편집 기능을 지원합니다.
  * *내보내기 제외 (눈 아이콘)*: 해당 세그먼트를 내보내기에서 완전히 제외합니다 (마커를 지우지 않아도 됨).
  * *미리보기 (재생 아이콘)*: 타임라인 재생 구간을 해당 클립의 시작/끝 프레임으로 자동 설정하여 빠르게 확인합니다.
  * *마커 이름 변경 / 삭제*: 텍스트 필드에서 즉시 이름을 바꾸거나 우측 휴지통 아이콘을 눌러 마커를 삭제할 수 있습니다.
  * *Reset Range (구간 초기화)*: 타임라인 재생 범위를 1프레임부터 마지막 마커 프레임까지 전체 애니메이션 길이로 복원합니다.
* **Targets**: 애니메이션 추출 대상 오브젝트의 총 수와 현재 선택된 활성 액션의 이름을 표시합니다.
* **Settings (설정)**:
  * *Export Path*: FBX/GLB 출력 폴더를 지정합니다. 기본값 `//Export/`는 저장된 `.blend` 파일 옆의 `Export` 폴더를 의미하며, 폴더가 없으면 자동으로 생성합니다.
  * *Auto Export (자동 저장)*: 파일 브라우저를 생략하고 **Export Path**에 `<blend 파일명>.fbx` 또는 `<blend 파일명>.glb`로 즉시 덮어씁니다. 먼저 `.blend` 파일을 저장해야 합니다. 저장된 파일명이 출력 파일명이 되고, `//Export/` 같은 상대 경로는 `.blend` 파일 옆을 기준으로 계산됩니다. 이 옵션은 **Quick Export (Marker Split)**에만 적용됩니다. 파일명과 위치를 직접 정하려면 끄고 일반 파일 브라우저를 사용하세요.
  * *Only Deform Bones*: 체크 시 컨트롤러용 뼈들을 제외하고, 실제 변형에 관여하는 스키닝용 뼈대(Deform Bone)만 내보내어 게임 엔진용 에셋 용량을 최적화합니다.
  * *Create Boundary Keys*: 활성화 시 F-Curve의 프레임 경계 구간에 키프레임을 삽입하여 프레임 유실로 인한 자세 흐트러짐을 방지합니다.
  * *Selected Only*: 체크 시 선택된 오브젝트만 추출 대상으로 삼습니다. GLB 내보내기에서는 스킨드 메시 계층이 빠지지 않도록 선택된 오브젝트의 모든 하위 오브젝트도 임시로 포함합니다.
  * *Open Folder After Export*: 내보내기에 성공하면 결과 파일이 있는 폴더를 엽니다.
* **Quick Export (Marker Split)**:
  * *Check FBX / Check GLB*: 임시 NLA 분할을 실제로 수행한 뒤 예상/생성 트랙 수와 모든 클립의 오브젝트별 `✓`, `⚠`, `✗` 결과를 팝업으로 표시합니다. Action/Strip 내용, 이름, 프레임 범위, Action Slot, 키프레임 및 내보내기 계층을 검사하고 임시 데이터는 즉시 제거합니다. 하드 오류는 Quick Export도 차단합니다.
  * *FBX*: 마커별로 애니메이션 테이크(Take)를 나눈 단일 `.fbx` 파일을 내보냅니다.
  * *GLB*: 마커별로 애니메이션 클립(Clip)을 나눈 단일 `.glb` 파일을 내보냅니다.
* **Manual NLA Tools (수동 도구 foldout)**: 마커 $\rightarrow$ NLA 영구 변환, NLA $\rightarrow$ Action 통합 액션 복구, 기존 NLA 수동 내보내기 및 트랙 전체 삭제 도구를 담고 있습니다.

---

## 🚀 설치 방법

1. 저장소를 `.zip` 파일로 다운로드합니다.
2. 블렌더를 실행하고 `Edit > Preferences > Addons`로 이동합니다.
3. 우측 상단의 `Install...` 버튼을 누르고 다운로드한 `.zip` 파일을 선택합니다.
4. 검색창에 "Hyper NLA Exporter"를 입력하고 체크박스를 켜서 애드온을 활성화합니다.

---

## 📖 사용 방법

1. 렌더 경로 파싱을 위해 먼저 `.blend` 파일을 저장합니다.
2. 애니메이션이 포함된 리그(Rig)/오브젝트를 선택합니다.
3. 타임라인 상에 분할할 지점을 마커로 설정합니다:
   * **마커 이름** = 출력될 클립 및 테이크 명칭.
   * **마커 위치(프레임)** = 해당 클립의 끝 프레임.
   * *예시*: 시작 프레임이 1일 때, 60프레임에 `Walk` 마커, 120프레임에 `Run` 마커를 배치하면 각각 `1-60` 구간(Walk), `61-120` 구간(Run)으로 자동 인지됩니다.
4. 사이드바 N패널에서 **K-Quick Tools** > **Hyper NLA Exporter** 패널을 엽니다.
5. 필요하면 **Export Path**를 지정합니다. 반복 내보내기라면 `.blend` 파일을 저장한 뒤 **Auto Export**를 켜세요. Quick Export의 **FBX** 또는 **GLB**를 누르면 해당 폴더의 `<blend 파일명>.fbx` 또는 `.glb`를 즉시 덮어씁니다. 파일명과 위치를 직접 정하려면 **Auto Export**를 끄고 일반 파일 브라우저를 사용하세요.

---

## ⚠️ 중요 주의 사항 및 기술적 참고 사항 (Technical Notes & Constraints)

1. **GLB/glTF 계층 구조 및 스케일 유지**:
   * `Selected Only`가 켜져 있으면 GLB 퀵 익스포트는 선택된 오브젝트와 그 아래의 모든 하위 계층을 임시로 선택한 뒤 `use_selection=True`로 내보냅니다. 내보내기가 끝나면 원래 선택 상태로 복원합니다.
   * 리그의 루트 오브젝트를 선택하면 연결된 스킨드 메시(Skinned Mesh)와 부속 오브젝트가 함께 포함되어, NLA 트랙 모드에서 계층 누락으로 인한 메시 복제나 잘못된 배치를 방지합니다.
   * `Selected Only`가 꺼져 있으면 씬 전체를 내보냅니다.
   * 또한 `export_rest_position_armature` 옵션을 자동으로 비활성화합니다. 이를 통해 조인트(Joint) 스케일이 강제로 1.0으로 초기화되는 현상을 방지하고, 원본 포즈의 본 스케일(예: 100배 스케일 등)을 온전히 유지합니다.
2. **Blender 5.1 Layered Action 애니메이션 구조**:
   * 블렌더 5.x의 최신 데이터 레이아웃(Action $\rightarrow$ Slot $\rightarrow$ Layer $\rightarrow$ Strip $\rightarrow$ Channelbag)을 지원합니다. 여러 오브젝트가 하나의 Action을 공유하더라도 각 오브젝트에 지정된 Action Slot의 F-Curve만 분할합니다.

---

## 📁 파일 구조

* `__init__.py`: 애드온 메타데이터 정의, 등록(Register) 및 모듈 리로딩을 제어합니다.

---

## 📄 라이선스 (License)

이 애드온은 블렌더 Python API(`bpy`)를 임포트하여 통합 실행되는 블렌더의 2차 저작물로서 **GNU GPL v3.0** 라이선스 하에 배포됩니다. 자세한 내용은 프로젝트 폴더의 [LICENSE](file:///c:/Users/user/AppData/Roaming/Blender%20Foundation/Blender/5.1/scripts/addons/hyper_NLA_exporter/LICENSE) 파일을 참고하십시오.
