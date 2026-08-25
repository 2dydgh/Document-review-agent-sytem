#!/usr/bin/env bash
#
# 공개 저장소로 내보내기 전 유출 검사.
#
#   scripts/check-before-public.sh [검사할폴더]
#
# **왜 있나** — 개발은 사내 Gitea 에서 하고, 끝나면 그 내용을 개인 저장소로 옮긴다.
# 그때 나가면 안 되는 것이 셋이다: 사내 서버 주소 · 고객사 검토 기준 · 고객 문서.
# 손으로 고르면 언젠가 `config/settings.toml` 을 딱 한 번 잘못 넣고, 그 한 번으로
# 사내 주소가 박힌다. git 은 지워도 과거 커밋에 남아 `git log -p` 로 다 읽힌다.
#
# 이 스크립트는 **막지 않는다. 찾아서 보여준다.** 무엇이 유출인지는 사람이 안다 —
# 예컨대 "SHN34" 가 옛 설계 문서의 실측 근거로 적혀 있는 것과, 고객사 검토 기준
# 파일에 들어 있는 것은 성질이 다르다. 스크립트가 판단하면 조용히 통과시키거나
# 조용히 막는다.
#
# 앞선 `export-shell.sh`(단방향 export)를 대신한다. 그쪽은 파일을 골라 복사하는
# 일까지 했는데, 사내 저장소가 원본이 되면서 방향이 뒤집혀 실효가 없어졌다 —
# 실제로 그 스크립트가 빼도록 되어 있던 팀 기준과 사내 주소가 이미 사내
# 저장소 안에 있다(의도된 것이다. 사내 자산이 사내 저장소로 간 것뿐이다).
# 남은 것은 **개인 저장소로 나갈 때의 검사** 하나뿐이라 그만큼만 남긴다.
#
set -uo pipefail

TARGET="${1:-.}"
cd "${TARGET}" || { echo "그런 폴더가 없다: ${TARGET}" >&2; exit 2; }

echo "검사 대상: $(pwd)"
echo ""

FOUND=0

# 검사에서 빼는 곳. 도구 상태·가상환경·빌드 부산물이고, .git 은 따로 본다.
PRUNE=(-name .git -o -name .venv -o -name node_modules -o -name __pycache__
       -o -name .omc -o -name .superpowers -o -name .pytest_cache
       -o -name .ruff_cache -o -name .claude)

scan() {   # scan <제목> <정규식> [설명]
  local title="$1" pattern="$2" note="${3:-}"
  local hits
  hits="$(find . \( "${PRUNE[@]}" \) -prune -o -type f -print 2>/dev/null \
          | xargs grep -lE "${pattern}" 2>/dev/null | sort)"
  if [[ -n "${hits}" ]]; then
    FOUND=1
    echo "⚠ ${title}"
    [[ -n "${note}" ]] && echo "   ${note}"
    printf '%s\n' "${hits}" | head -12 | sed 's/^/     /'
    local n; n="$(printf '%s\n' "${hits}" | wc -l)"
    (( n > 12 )) && echo "     … 외 $((n - 12))개"
    echo ""
  fi
}

# ── 1. 사내 서버 주소 ──────────────────────────────────────────────────────
# 배포마다 다른 값이라 코드에도 설정 파일에도 없어야 한다 — 환경변수로 준다
# (LLM_QWEN_URL · LLM_OCR_URL). config/settings.toml 이 늘 걸리는 자리다.
scan "사내 서버 주소" '10\.10\.10\.[0-9]+|:(9001|9002|19640)/v1' \
     "환경변수(LLM_QWEN_URL·LLM_OCR_URL)로 옮기고 파일에서 빼세요."

# ── 2. 고객사·계통 이름 ────────────────────────────────────────────────────
# 옛 설계 문서에는 실측 근거로 정당하게 적혀 있다("SHN34 SRS 380개"). 팀 기준
# 파일·설정에 있으면 그건 다른 얘기다 — 그래서 막지 않고 목록만 낸다.
scan "고객사·계통 이름" 'SHN34|SKN56|KEPCO|DOOSAN|11C74|Z1105[0-9]' \
     "docs/ 의 실측 기록은 정상. presets/·config/ 에 있으면 빼세요."

# ── 3. 팀 검토 기준 ────────────────────────────────────────────────────────
# 고객사 요구사항에서 뽑은 도메인 데이터다. 공통 기준(common.yaml)은 우리가 쓴
# 것이라 나가도 된다.
if compgen -G "presets/criteria/teams/*.yaml" > /dev/null; then
  # items 가 빈 껍데기는 팀 목록용이라 내용이 없다 — 그건 나가도 된다.
  filled="$(grep -l "^- 'no'" presets/criteria/teams/*.yaml 2>/dev/null || true)"
  if [[ -n "${filled}" ]]; then
    FOUND=1
    echo "⚠ 팀 검토 기준 (내용이 든 것)"
    echo "   고객사 요구사항에서 뽑은 도메인 데이터입니다."
    printf '%s\n' "${filled}" | sed 's/^/     /'
    echo ""
  fi
fi

# ── 4. 고객 문서 ───────────────────────────────────────────────────────────
for d in data .docreview; do
  if [[ -d "${d}" ]] && [[ -n "$(find "${d}" -type f -print -quit 2>/dev/null)" ]]; then
    FOUND=1
    echo "⚠ ${d}/ 에 파일이 있습니다 ($(find "${d}" -type f | wc -l)개)"
    echo "   고객 문서·검토 이력입니다. 폴더째 빼세요."
    echo ""
  fi
done

# ── 5. git 히스토리 ────────────────────────────────────────────────────────
# **여기가 제일 놓치기 쉽다.** 파일을 지우고 커밋해도 과거 커밋에 남는다.
# 새 저장소로 옮길 때는 히스토리를 안 가져가는 것이 유일하게 확실한 방법이다.
if [[ -d .git ]]; then
  n="$(git rev-list --count HEAD 2>/dev/null || echo 0)"
  if (( n > 1 )); then
    echo "ℹ git 히스토리 ${n}개 커밋"
    echo "   파일을 지워도 과거 커밋에 남습니다 (git log -p 로 읽힙니다)."
    echo "   공개 저장소로는 히스토리를 **안 가져가는** 쪽이 확실합니다:"
    echo "     rsync -a --exclude .git ./ ../새폴더/ && cd ../새폴더 && git init"
    echo ""
  fi
fi

# ── 요약 ───────────────────────────────────────────────────────────────────
if (( FOUND )); then
  echo "걸린 것이 있습니다. 위 목록을 보고 판단하세요 — 스크립트는 막지 않습니다."
  exit 1
fi
echo "✓ 걸린 것 없음"
