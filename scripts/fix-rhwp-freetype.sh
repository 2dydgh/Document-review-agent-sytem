#!/usr/bin/env bash
# rhwp-python 0.8.1 linux 휠 고치기 — `uv sync` 뒤에 한 번 돌린다.
#
# 왜 필요한가: 휠이 번들한 freetype 은 FT_Palette_Data_Get 을 갖고 있지 않은데
# _rhwp.abi3.so 는 그 심볼을 요구한다(FreeType >= 2.10). 번들 lib 이 RPATH 우선이라
# 멀쩡한 시스템 freetype 이 안 쓰이고 `import rhwp` 가 ImportError 로 죽는다.
# 번들본을 시스템 freetype 으로 덮어쓰면 끝난다.
#
# 상류가 휠을 고치면 이 스크립트도 이 호출도 지운다.
set -euo pipefail

VENV="${1:-.venv}"
LIBS=$(echo "$VENV"/lib/python*/site-packages/rhwp_python.libs)

if [ ! -d "$LIBS" ]; then
    echo "rhwp_python.libs 없음: $LIBS — rhwp-python 이 설치됐는지 확인" >&2
    exit 1
fi

# awk 에 exit 를 쓰면 ldconfig 가 SIGPIPE 로 죽어 pipefail 에 걸린다 — 끝까지 읽고 첫 줄만 쓴다.
SYS_FT=$(ldconfig -p | awk '/libfreetype\.so\.6/ {print $NF}' | head -1)
if [ -z "$SYS_FT" ]; then
    echo "시스템 freetype 없음. 설치: sudo apt install libfreetype6" >&2
    exit 1
fi

# 번들 파일명에 붙은 해시는 릴리스마다 바뀐다 — glob 로 찾는다.
found=0
for bundled in "$LIBS"/libfreetype-*.so.6; do
    [ -e "$bundled" ] || continue
    cp "$SYS_FT" "$bundled"
    echo "교체: $(basename "$bundled") <- $SYS_FT"
    found=1
done

if [ "$found" -eq 0 ]; then
    echo "번들 freetype 이 없다 — 상류가 고쳤을 수 있다. 그대로 import 를 시험해 본다." >&2
fi

"$VENV"/bin/python -c "import rhwp; print('import rhwp OK — core', rhwp.rhwp_core_version())"
