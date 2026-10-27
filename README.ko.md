🌐 [English](README.md) | 🇰🇷 [한국어](README.ko.md)

# 🎬 Hyper NLA Exporter 사용자 가이드

**타임라인 하나에 애니메이션을 만들고, 클립 끝마다 마커를 찍고, 한 번 클릭합니다.** Hyper NLA Exporter는 그 타임라인을 이름 붙은 FBX Take나 GLB 애니메이션으로 내보냅니다. NLA 트랙을 손으로 만들 필요가 없습니다.

<p align="center">
  <img src="https://img.shields.io/badge/Blender-5.1+-306EE8?logo=blender&logoColor=white&style=for-the-badge" alt="Blender Version">
  <img src="https://img.shields.io/badge/Format-FBX%20%2F%20GLB-E04E39?style=for-the-badge" alt="Format support">
  <img src="https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge" alt="License">
</p>

```
Timeline   1 ─────── Idle ─────── 40 ─────── Walk ─────── 80 ───────── Attack ───────── 140
Markers                           ▲ Idle                  ▲ Walk                        ▲ Attack
Export     Idle (frames 1–40)       Walk (frames 1–40)       Attack (frames 1–60)   → one .fbx / .glb
```

---

## 🤔 왜 만들었나

블렌더의 NLA 에디터는 애니메이션을 **겹쳐 쌓기** 위한 도구입니다. Unity의 Timeline처럼, 켜져 있는 트랙을 모두 동시에 평가해 아래에서 위로 합칩니다. 반면 게임 엔진에 필요한 것은 Animator Controller처럼 **서로 독립된 클립 목록**입니다. 블렌더에는 이런 목록이 없어서 FBX·glTF 익스포터는 NLA 트랙을 클립 목록으로 빌려 쓰고, 겹쳐 쌓는 규칙까지 함께 따라옵니다.

* 뮤트나 솔로 체크 하나만 놓쳐도 내보낸 파일에서 클립끼리 섞입니다.
* 스트립의 기본 Extrapolation인 *Hold*가 첫 포즈로 아래 트랙의 클립을 덮습니다.
* 남아 있는 활성 Action이 모든 트랙 위에서 다시 평가됩니다.
* 클립에 키가 없는 채널은 아래 트랙의 움직임이 새어 나옵니다.

이 애드온은 NLA를 직접 다룰 일이 없게 합니다. Action 하나를 만들고 마커로 클립을 표시하면, Quick Export가 내보내는 순간에만 NLA 트랙을 만들고, 기존 NLA는 격리하고, 결과를 검사한 뒤 모두 되돌립니다.

| | NLA 트랙 직접 구성 | Hyper NLA Exporter |
|---|---|---|
| 클립 정의 | Action마다 트랙에 넣고 이름 짓고 위치 맞추기 | 클립 끝에 마커 찍기 |
| 클립 하나 미리보기 | 트랙 뮤트/솔로, 활성 Action 해제 | 클립 줄의 ▶ 버튼 |
| 체크 실수 하나 | 내보낸 파일에서 클립이 조용히 섞임 | 기존 NLA는 내보내는 동안 격리 후 복원 |
| 여러 오브젝트·Empty·Shape Key | 오브젝트마다 트랙 세트를 손으로 맞춤 | 함께 분할해 GLB 하나로 |
| 실수 발견 시점 | 엔진에 가져온 뒤 | 내보내기 전 **Check FBX / Check GLB** |
| 수정 후 다시 내보내기 | 구성 작업 반복 | 클릭 한 번, Auto Export가 안전하게 덮어쓰기 |

> [!IMPORTANT]
> **사용 목적 및 지원 범위**: 이 애드온은 **Unity 게임 엔진용 FBX Animation Take** 추출 및 **웹 기반 서비스용 GLB NLA 애니메이션** 추출을 위해 특화되어 제작되었습니다. 명시된 목적 외의 다른 용도나 환경에서의 정상적인 작동은 보장하지 않습니다.

---

## 🌟 주요 기능 (Key Features)

* ⚡ **마커 기반 자동 분할**: 패널의 **First Clip Start**와 타임라인 마커의 이름·위치를 이용해 각 애니메이션 클립의 이름과 구간을 자동으로 파싱합니다.
* 🚀 **원클릭 퀵 익스포트**: 마커 구간별 액션 분할, 프레임 1번부터 시작하도록 자동 리타이밍, 파일 내보내기, 임시 NLA 정리 작업을 단 한 번의 클릭으로 일괄 수행합니다.
* 💾 **Auto Export (자동 저장)**: 파일 브라우저를 열지 않고, 지정한 위치에 예측 가능한 이름으로 FBX 또는 GLB를 바로 저장하고 덮어쓸 수 있습니다. 내보내기에 실패하면 이전 파일을 덮어쓰지 않습니다.
* 🔄 **비파괴 워크플로우**: 작업공간의 활성 액션과 NLA 상태를 전혀 훼손하지 않습니다. 모든 분할 작업 및 NLA 변환은 렌더링 순간에만 임시 메모리 내에서 수행됩니다.
* 📐 **경계 커브 보존**: 세그먼트의 첫 프레임과 끝 프레임에 누락된 키를 채우고, 베지어 핸들을 원본 곡선대로 절단하고, 마커 위에 놓인 키의 자동 핸들을 유지하고, 마커에 잘린 Easing 곡선은 프레임 단위로 베이크하여 분할 후 포즈와 움직임 곡선을 함께 보존합니다.
* ✅ **안전한 내보내기**: 중복/빈 클립 이름, 2프레임 미만 클립, 같은 프레임에 겹친 마커, 잘못된 마커, 누락된 Action Slot과 F-Curve, 범위 안의 키 유무, 선택에서 빠진 스킨드 메시를 사전에 확인합니다. 키프레임이 하나도 없는 Action은 내보내기 대상으로 세지 않고 무시합니다. 내보내기 범위의 모든 오브젝트와 Shape Key의 기존 NLA 트랙은 Quick Export 동안 임시 격리하고 완료 후 원래 상태로 복원합니다. 활성 Action 없이 NLA만 가진 경우도 포함합니다.
* 📂 **완료 폴더 열기**: 내보내기에 성공하면 생성된 FBX/GLB가 있는 폴더를 자동으로 엽니다.
* 🗜️ **GLB Draco 압축**: 압축 레벨과 양자화 비트를 조절할 수 있는 선택형 메시 압축입니다.
* ⚙️ **수동 NLA 제어 도구**: 마커를 이용해 영구적인 NLA 트랙을 생성하거나, 분할된 NLA들을 다시 하나의 긴 통합 액션으로 합치고, 깔끔하게 정리하는 복구용 도구를 제공합니다.
* 🧪 **회귀 테스트**: 모든 수정에는 Blender 백그라운드 테스트가 함께 들어갑니다. `tests/run_tests.ps1`이 Blender 5.1과 5.2에서 테스트를 실행하며, 내보낸 파일을 다시 불러오거나 GLB에서 직접 읽어 실제 애니메이션 값을 확인합니다.



## 🛠️ 패널 인터페이스 개요 (Panel Interface Overview)

3D Viewport > Sidebar (N-패널) > **K-Quick Tools** 탭의 **Hyper NLA Exporter** 패널에 위치해 있습니다.

```
┌─────────────────────────────────────────────┐
│ ▼ Hyper NLA Exporter                        │
├─────────────────────────────────────────────┤
│ ┌─ Marker Segments ───────────────────────┐ │
│ │ First Clip Start: [ 1 ]                 │ │
│ │ (o) [>] [ Idle   ]  1~40 (40f)    [x]   │ │
│ │ (o) [>] [ Walk   ] 41~80 (40f)    [x]   │ │
│ │ [ Reset Range ]                         │ │
│ └─────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────┐ │
│ │ Quick Export: 1 Actions                 │ │
│ │ Active Action: Rig_Action               │ │
│ └─────────────────────────────────────────┘ │
│ ┌─ Settings ──────────────────────────────┐ │
│ │ Export Path: [ //Export/        ]       │ │
│ │ [ ] Auto Export                         │ │
│ │ [ ] Only Deform Bones                   │ │
│ │ [x] Create Boundary Keys                │ │
│ │ [x] Selected Only                       │ │
│ │ [x] Open Folder After Export            │ │
│ │ [ ] GLB Draco Compression               │ │
│ └─────────────────────────────────────────┘ │
│ ┌─ Quick Export (Marker Split) ───────────┐ │
│ │ [ Check FBX ]        [ Check GLB ]      │ │
│ │ [    FBX    ]        [    GLB    ]      │ │
│ │ FBX: One rig only · GLB: Multi-rig      │ │
│ └─────────────────────────────────────────┘ │
│ ▶ Manual NLA Tools                          │
└─────────────────────────────────────────────┘
```

* **Marker Segments**: 타임라인 마커를 기반으로 감지된 애니메이션 클립들을 표시하며, 인라인 편집 기능을 지원합니다.
  * *First Clip Start*: 첫 번째 클립을 원본 액션의 몇 프레임부터 읽을지 지정합니다. 기본값은 1이며, 출력 클립은 기존처럼 프레임 1부터 시작하도록 리타이밍됩니다.
  * *내보내기 제외 (눈 아이콘)*: 해당 세그먼트를 내보내기에서 완전히 제외합니다 (마커를 지우지 않아도 됨).
  * *미리보기 (재생 아이콘)*: 타임라인 재생 구간을 해당 클립의 시작/끝 프레임으로 자동 설정하여 빠르게 확인합니다.
  * *마커 이름 변경 / 삭제*: 텍스트 필드에서 즉시 이름을 바꾸거나 우측 휴지통 아이콘을 눌러 마커를 삭제할 수 있습니다.
  * *Reset Range (구간 초기화)*: 타임라인 재생 범위를 **First Clip Start**부터 마지막 마커 프레임까지 복원합니다.
* **Targets**: 애니메이션 추출 대상 오브젝트의 총 수와 현재 선택된 활성 액션의 이름을 표시합니다.
* **Settings (설정)**:
  * *Export Path*: FBX/GLB 출력 폴더를 지정합니다. 기본값 `//Export/`는 저장된 `.blend` 파일 옆의 `Export` 폴더를 의미하며, 폴더가 없으면 자동으로 생성합니다.
  * *Auto Export (자동 저장)*: 파일 브라우저를 생략하고 **Export Path**에 `<blend 파일명>.fbx` 또는 `<blend 파일명>.glb`로 즉시 덮어씁니다. 먼저 `.blend` 파일을 저장해야 합니다. 저장된 파일명이 출력 파일명이 되고, `//Export/` 같은 상대 경로는 `.blend` 파일 옆을 기준으로 계산됩니다. 이 옵션은 **Quick Export (Marker Split)**에만 적용됩니다. 파일명과 위치를 직접 정하려면 끄고 일반 파일 브라우저를 사용하세요.
  * 모든 내보내기는 먼저 대상 옆의 임시 폴더에 기록됩니다. Blender exporter가 성공을 보고하고 새 파일이 비어 있지 않을 때만 기존 파일과 교체하므로, 취소되거나 실패한 내보내기는 마지막 정상 파일을 그대로 남깁니다.
  * *Only Deform Bones*: 체크 시 컨트롤러용 뼈들을 제외하고, 실제 변형에 관여하는 스키닝용 뼈대(Deform Bone)만 내보내어 게임 엔진용 에셋 용량을 최적화합니다.
  * *Create Boundary Keys*: 활성화 시 F-Curve의 프레임 경계 구간에 키프레임을 삽입하여 프레임 유실로 인한 자세 흐트러짐을 방지합니다. 꺼져 있어도 FBX/GLB 클립은 마커 구간 전체 길이를 유지하며, 곡선은 클립 양 끝까지 첫/마지막 키 값을 유지합니다.
  * *Selected Only*: 체크 시 선택된 오브젝트만 추출 대상으로 삼습니다. 퀵 익스포트에서는 스킨드 메시 계층이 빠지지 않도록 선택된 오브젝트의 모든 하위 오브젝트도 임시로 포함하며, FBX와 GLB에 모두 적용됩니다.
  * *Open Folder After Export*: 내보내기에 성공하면 결과 파일이 있는 폴더를 엽니다.
  * *GLB Draco Compression*: GLB 메시를 Draco(`KHR_draco_mesh_compression`)로 압축하고, 압축 레벨과 양자화 비트를 조절할 수 있습니다. 모든 GLB 내보내기(Quick Export, 기존 NLA 내보내기)에 적용되며 FBX에는 영향이 없습니다. 불러오는 엔진에 Draco 디코더가 있어야 합니다(예: Unity의 glTFast + Draco 패키지). Blender의 Draco 라이브러리가 없으면 경고와 함께 압축 없이 내보냅니다.
* **Quick Export (Marker Split)**:
  * 버튼 아래의 형식 안내는 현재 범위에 애니메이션 대상이 여러 개 있을 때 빨간색 경고로 바뀝니다. FBX는 애니메이션 리그 하나만 지원하고 GLB는 다중 리그 씬을 지원합니다.
  * *Check FBX / Check GLB*: 임시 NLA 분할을 실제로 수행한 뒤 예상/생성 트랙 수를 팝업으로 표시합니다. 모든 클립이 정상인 오브젝트는 `✓` 한 줄로 묶고, 문제가 있는 오브젝트만 박스로 `⚠`, `✗` 클립을 보여줍니다. 목록이 길면 팝업에서는 일부만 보여주고 전체 목록은 System Console에 출력합니다. Action/Strip 내용, 이름, 프레임 범위, Action Slot, 키프레임 및 내보내기 계층을 검사하고 임시 데이터는 즉시 제거합니다. 하드 오류는 Quick Export도 차단합니다. 클립 구간 안에 키가 없는 오브젝트(예: 일부 클립에서만 움직이는 Empty)는 클립마다 한 줄로 요약합니다. Create Boundary Keys가 켜져 있으면 자세를 유지하므로 정보로, 꺼져 있으면 해당 오브젝트가 그 클립에서 빠지므로 경고로 표시합니다.
  * *FBX*: 활성 Action을 가진 애니메이션 오브젝트 하나를 마커별 Take로 나누어 단일 `.fbx` 파일로 내보냅니다. 애니메이션 리그와 Action이 없는 메시 계층은 함께 선택할 수 있지만, 활성 Action을 가진 오브젝트가 여러 개면 Blender FBX exporter가 같은 이름의 Take를 안전하게 합치지 못하므로 내보내기를 차단합니다.
  * *GLB*: 여러 애니메이션 리그가 포함된 씬도 마커별 클립으로 나누어 단일 `.glb` 파일로 내보냅니다.
* **Manual NLA Tools (수동 도구 foldout)**: 마커 $\rightarrow$ NLA 영구 변환, NLA $\rightarrow$ Action 통합 액션 복구, 기존 NLA 수동 내보내기 및 트랙 전체 삭제 도구를 담고 있습니다.



## 🚀 설치 방법

1. 저장소를 `.zip` 파일로 다운로드합니다.
2. 블렌더를 실행하고 `Edit > Preferences > Addons`로 이동합니다.
3. 우측 상단의 `Install...` 버튼을 누르고 다운로드한 `.zip` 파일을 선택합니다.
4. 검색창에 "Hyper NLA Exporter"를 입력하고 체크박스를 켜서 애드온을 활성화합니다.



## 📖 사용 방법

1. 렌더 경로 파싱을 위해 먼저 `.blend` 파일을 저장합니다.
2. 애니메이션이 포함된 리그(Rig)/오브젝트를 선택합니다.
3. 타임라인 상에 분할할 지점을 마커로 설정합니다:
   * **First Clip Start** = 첫 클립이 원본 액션에서 시작되는 프레임(기본값 `1`).
   * **마커 이름** = 출력될 클립 및 테이크 명칭.
   * **마커 위치(프레임)** = 해당 클립의 끝 프레임.
   * *예시*: 시작 프레임이 1일 때, 60프레임에 `Walk` 마커, 120프레임에 `Run` 마커를 배치하면 각각 `1-60` 구간(Walk), `61-120` 구간(Run)으로 자동 인지됩니다.
4. 사이드바 N패널에서 **K-Quick Tools** > **Hyper NLA Exporter** 패널을 엽니다.
5. 필요하면 **Export Path**를 지정합니다. 반복 내보내기라면 `.blend` 파일을 저장한 뒤 **Auto Export**를 켜세요. Quick Export의 **FBX** 또는 **GLB**를 누르면 해당 폴더의 `<blend 파일명>.fbx` 또는 `.glb`를 즉시 덮어씁니다. 파일명과 위치를 직접 정하려면 **Auto Export**를 끄고 일반 파일 브라우저를 사용하세요.



## ⚠️ 중요 주의 사항 및 기술적 참고 사항 (Technical Notes & Constraints)

1. **GLB/glTF 계층 구조 및 스케일 유지**:
   * `Selected Only`가 켜져 있으면 퀵 익스포트는 선택된 오브젝트와 그 아래의 모든 하위 계층을 임시로 선택한 뒤 `use_selection=True`로 내보냅니다. FBX와 GLB에 모두 적용되므로 리그만 선택해도 스킨드 메시가 빠지지 않습니다. 내보내기가 끝나면 애드온이 추가로 선택한 오브젝트만 해제하므로 원래 선택 상태는 그대로 유지됩니다.
   * 리그의 루트 오브젝트를 선택하면 연결된 스킨드 메시(Skinned Mesh)와 부속 오브젝트가 함께 포함되어, NLA 트랙 모드에서 계층 누락으로 인한 메시 복제나 잘못된 배치를 방지합니다.
   * `Selected Only`가 꺼져 있으면 씬 전체를 내보냅니다.
   * 또한 `export_rest_position_armature` 옵션을 자동으로 비활성화합니다. 이를 통해 조인트(Joint) 스케일이 강제로 1.0으로 초기화되는 현상을 방지하고, 원본 포즈의 본 스케일(예: 100배 스케일 등)을 온전히 유지합니다.
2. **클립 길이는 최소 2프레임이어야 합니다**:
   * **First Clip Start**와 같은 프레임에 마커를 두거나 마커 두 개를 연속된 프레임에 두면 1프레임 클립이 만들어집니다. Blender는 길이 0인 NLA Strip을 만들 수 없어 2프레임으로 늘리므로, 내보낸 Take가 마커 구성과 달라집니다.
   * 사전 검사가 해당 클립 이름을 알려주고 내보내기를 차단하며, 패널에서도 해당 행이 빨간색으로 표시됩니다. 마커를 최소 1프레임 뒤로 옮기거나 눈 아이콘으로 뮤트하세요.
   * **같은** 프레임에 놓인 마커 두 개는 둘 다 클립의 끝이 될 수 없어 하나가 조용히 사라집니다. 사전 검사와 Markers → NLA는 해당 프레임과 마커 이름을 오류로 알리고, 패널에도 빨간색으로 표시합니다. 마커 하나를 옮기거나 둘 다 뮤트하세요.
3. **빈 Action은 무시하고, 잘못된 슬롯은 차단합니다**:
   * 키프레임이 하나도 없는 Action이 스킨드 메시에 남아 있어도 내보내기 대상으로 세지 않습니다. 이 처리가 없으면 아무것도 기여하지 않는 메시가 두 번째 애니메이션 오브젝트로 잡혀 FBX Quick Export가 막힙니다.
   * 반대로 Action에 F-Curve가 있는데 오브젝트가 비어 있는 슬롯을 가리키는 경우에는 애니메이션이 빠진 채로 내보내지므로, 오브젝트와 Action 이름을 알려주는 사전 검사 오류로 남깁니다.
4. **내보내기 결과는 플레이헤드 위치에 좌우되지 않습니다**:
   * Blender FBX exporter는 각 본의 기본 `Lcl Translation` / `Lcl Rotation`을 내보낼 때의 현재 프레임 포즈로 기록합니다. 특정 본에 대해 이 기본값으로 폴백하는 뷰어나 엔진에서는, 내보낼 때 플레이헤드가 어디 있었는지에 따라 한 클립이 다른 클립의 포즈를 그대로 들고 있는 현상이 생깁니다.
   * Quick Export는 임시 분할을 만들기 **전에** 플레이헤드를 **First Clip Start**로 고정합니다. 기존 NLA가 켜진 상태로 한 번, 기존 NLA를 뮤트한 뒤 다시 한 번 그 프레임에서 씬을 평가합니다. 따라서 분할이 모든 클립에 상수로 기록하는 값(키가 없는 본 트랜스폼, 예: Root 스케일 100 / 드라이버 결과 / 뮤트된 NLA가 남긴 값)은 플레이헤드가 있던 위치가 아니라 **First Clip Start**에서 읽습니다. 내보내는 동안 플레이헤드는 그 위치에 머물고 끝나면 원래 위치로 되돌리므로, 같은 씬은 항상 같은 파일을 만듭니다.
5. **Blender 5.1 Layered Action 애니메이션 구조**:
   * 블렌더 5.x의 최신 데이터 레이아웃(Action $\rightarrow$ Slot $\rightarrow$ Layer $\rightarrow$ Strip $\rightarrow$ Channelbag)을 지원합니다. 여러 오브젝트가 하나의 Action을 공유하더라도 각 오브젝트에 지정된 Action Slot의 F-Curve만 분할합니다.
6. **하위 계층도 같은 마커로 분할합니다**:
   * Quick Export의 검사·분할·내보내기는 동일한 표시 가능한 하위 계층을 대상으로 합니다. 애니메이션이 없는 부모를 선택해도 자식의 애니메이션을 찾습니다. 애니메이션이 있는 자식이 여러 개라면 직접 여러 개를 선택했을 때와 동일하게 FBX 단일 오브젝트 제한이 적용됩니다.
7. **F-Curve Modifier 보존**:
   * Cycles·Noise 같은 활성 Modifier와 샘플 곡선은 원본 시간에서 평가하여 1프레임 간격으로 베이크합니다. 이 경우 Create Boundary Keys가 꺼져 있어도 클립 양 끝을 포함합니다. 일반 키프레임 곡선은 베지어 보간을 유지하며, 뮤트된 곡선과 그룹은 제외합니다.
   * Easing 보간(Quad, Sine, Back, Elastic 등)은 키 구간 전체가 클립 안에 있으면 Easing·Back·Amplitude·Period 값을 그대로 유지합니다. 마커가 이런 구간을 자르면 Easing 공식을 재사용할 수 없으므로 잘린 부분만 1프레임 간격으로 베이크합니다.
   * 자동 핸들(Auto, Auto Clamped, Vector)은 이웃 키에 따라 계산됩니다. 클립이 키의 이웃을 잘라내면(마커 위에 정확히 놓인 키 포함) 그 키의 핸들을 원본 곡선의 좌표로 Free 핸들로 고정합니다. 이웃이 클립 안에 그대로 있는 키는 자동 핸들을 유지합니다. NLA → Action도 같은 규칙을 따릅니다.
   * NLA → Action은 선택한 오브젝트를 오브젝트마다 슬롯을 가진 하나의 Action으로 합칩니다. 같은 이름의 스트립이 하나의 클립이 되고, 같은 프레임에 겹쳐 놓은 클립(예: Yes/No 버전)은 차례로 이어 붙입니다. 클립마다 끝 프레임에 마커를 하나씩 만들어 Markers → NLA로 다시 나눌 수 있습니다. 스트립 구간은 클립을 내보낼 때와 같은 방식으로 복사하므로, 키가 일찍 끝나는 커브도 클립이 끝날 때까지 값을 유지하고 다음 클립 쪽으로 흘러가지 않습니다. 뮤트된(체크 해제된) NLA 트랙은 제외합니다.
   * 채널 그룹(예: 본별 그룹)은 모든 클립에 그대로 복사됩니다.
8. **Shape Key 애니메이션은 GLB를 사용합니다**:
   * Quick GLB는 Shape Key Action을 오브젝트·본 애니메이션과 같은 마커 클립으로 분할합니다. 표정만 움직이는 메시와 선택한 리그 아래의 메시도 포함합니다.
   * Morph Target 보존을 위해 Shape Key가 포함된 내보내기에서는 기본 메시를 사용하며, 해당 내보내기의 모든 메시에서 Armature 외의 Modifier를 적용하지 않습니다. 영향을 받는 메시는 사전 검사에서 경고합니다. Shape Key가 없는 내보내기는 기존처럼 Modifier를 적용하며, 스키닝은 계속 지원합니다.
   * Blender의 NLA Take별 FBX 내보내기는 Shape Key Action을 함께 동기화하지 못하므로 Quick FBX는 활성 Shape Key 애니메이션을 감지하면 안내 후 차단합니다. 뼈대와 표정이 함께 들어가는 클립은 Quick GLB를 사용하세요.
9. **수동 도구의 원본 데이터 보존**:
   * Markers → NLA는 요청한 클립을 모두 만든 뒤 기존 트랙을 교체합니다. 빈 클립이나 생성 오류가 있으면 변환을 취소하고 원본 애니메이션을 유지합니다.
   * 변환된 Strip의 Extrapolation은 **Nothing**이므로 각 트랙은 자기 클립 구간에서만 재생되고, 첫 포즈로 아래 트랙의 클립을 가리지 않습니다.
   * NLA Strip 이름은 오브젝트마다 고유해야 합니다. Clear Existing NLA가 클립과 같은 이름의 기존 Strip을 지우면 새 Strip이 클립 이름을 되찾고, 같은 이름의 Strip을 남겨 두면 새 Strip에 `.001`이 붙으며 이를 경고로 알립니다. Quick Export는 이런 기존 Strip의 이름을 잠시 바꿔 두므로 클립 이름은 항상 마커 이름과 같습니다.
   * 변환·병합·Cleanup은 직접 만든 Action의 연결을 제거하기 전에 Fake User를 지정하므로 저장 후 다시 열어도 남습니다. 애드온이 생성한 Action은 더 이상 사용하지 않을 때 해제합니다.
10. **NLA 평가와 Constraint**:
   * Quick Export는 내보내는 동안 분할 대상 오브젝트의 NLA 평가를 켜고, 끝나면 원래 설정으로 되돌립니다. 따라서 NLA 평가를 꺼 둔 오브젝트도 FBX에 움직임이 기록됩니다.
   * Quick GLB는 오브젝트마다 클립을 따로 샘플링하므로 **다른 애니메이션 오브젝트**를 따라가는 Constraint(Copy Location, Child Of, 다른 오브젝트를 IK 타깃으로 쓰는 경우 등)는 잘못된 움직임으로 기록되고, Constraint만 있는 오브젝트는 애니메이션이 빠집니다. Preflight가 해당 조합을 경고합니다. 먼저 **Object > Animation > Bake Action**에서 *Visual Keying*과 *Clear Constraints*를 켜고 따라가는 오브젝트를 베이크하세요. 같은 아마추어 안의 본끼리 거는 Constraint는 영향이 없습니다.



## 📁 파일 구조

* `__init__.py`: 패키지 진입점, 애드온 메타데이터 및 기존 접근 호환성을 관리합니다.
* `action_utils.py`: Blender 5.1 Action, Slot, Channelbag, 분할 및 병합 헬퍼를 관리합니다.
* `clips.py`: 타임라인 마커를 애니메이션 클립 구간으로 해석합니다.
* `export_utils.py`: 사전 검사, 내보내기 경로 및 완료 처리를 관리합니다.
* `nla_split.py`: Quick Export용 임시 NLA를 비파괴 방식으로 생성하고 복구합니다.
* `operators.py`: 검사, 내보내기, 변환, 미리보기 및 정리 Operator를 정의합니다.
* `ui.py`: 3D View 사이드바 패널과 임시 UI 상태를 정의합니다.
* `registration.py`: Blender 클래스와 RNA 속성의 등록 및 해제를 관리합니다.
* `tests/`: Blender 백그라운드 스모크 테스트와 실제 내보내기 회귀 테스트를 포함합니다.



## 📄 라이선스 (License)

이 애드온은 블렌더 Python API(`bpy`)를 임포트하여 통합 실행되는 블렌더의 2차 저작물로서 **GNU GPL v3.0** 라이선스 하에 배포됩니다. 자세한 내용은 프로젝트 폴더의 [LICENSE](file:///c:/Users/user/AppData/Roaming/Blender%20Foundation/Blender/5.1/scripts/addons/hyper_NLA_exporter/LICENSE) 파일을 참고하십시오.
