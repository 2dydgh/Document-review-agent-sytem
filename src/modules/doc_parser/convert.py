"""포맷 → PDF 변환. 뷰어가 언제나 PDF만 다루게 한다.

엔진은 LibreOffice(`soffice`) 하나. docx는 직접 변환(진짜 원본), hwpx는 엔진이 뽑은
마크다운형 텍스트를 HTML로 조립해 변환(재현) — hwpx는 LibreOffice가 직접 못 연다.
soffice는 시스템 바이너리라 지연 탐지한다. 없으면 화면에 설치법을 띄운다.
"""
from __future__ import annotations

import html as _html
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path

from .ingestion.base import UnsupportedFormatError, load_document
from .ptab import rewrite_ptabs


class _SofficeFailed(RuntimeError):
    """soffice 가 온전한 PDF 를 못 냈다. **반환코드를 들고 다닌다** —
    "확장 미설치"와 "크래시"를 구분해 안내해야 하기 때문이다. 맨 RuntimeError 로
    올리면 그 구분이 사라져 크래시가 "H2Orestart 를 설치하세요"로 둔갑한다.
    RuntimeError 를 물려받는 것은 hwpx 폴백이 그것을 잡고 있어서다."""

    def __init__(self, returncode: int, detail: str):
        super().__init__(detail)
        self.returncode = returncode


class ConvertUnavailable(Exception):
    """soffice가 PATH에 없다. 설치 방법을 화면에 그대로 띄운다."""


class ConvertTimeout(ConvertUnavailable):
    """시한 안에 변환이 안 끝났다.

    **폴백 대상이 아니다.** hwpx 는 변환이 실패하면 추출 텍스트 재현본으로
    물러서는데, 시한 초과는 soffice 가 물려 있다는 뜻이라 폴백도 같은 시한을
    한 번 더 쓴다(2분 + 2분). 그래서 이것만 따로 세워 폴백 handler 가 안 잡게
    한다 — ConvertUnavailable 은 RuntimeError 계열이 아니다."""


_TIMEOUT = 120

# soffice 를 한 번에 하나만 돌린다. 프로파일을 격리해도(-env:UserInstallation)
# 동시에 두 변환이 겹치면 **segfault(139)** 로 죽는다 — 실측으로 그랬다.
# H2Orestart 는 Java 기반이고 동시 실행에 안전하지 않은 것으로 보인다.
# 대가는 두 번째 사람이 기다리는 것이다(변환 3~9초). 크래시보다 낫다.
# 프로세스 안에서만 막는다 — 서버를 여러 프로세스로 띄우면 작업 큐가 맡아야 한다.
_SOFFICE_LOCK = threading.Lock()


#: 사내 문서가 쓰는데 리눅스에 없는 글꼴 → 대신 쓸 글꼴.
#:
#: **실측으로 정했다.** docx 는 Word 가 계산한 쪽수를 docProps/app.xml 에 남기므로
#: 그것을 정답지로 쓸 수 있다. 사내 문서 22개를 매핑별로 변환해 재보면:
#:
#:     매핑 없음(지금)   쪽수 정확 13/22 · 평균 오차 1.0쪽
#:     고딕만 매핑        쪽수 정확 20/22 · 평균 오차 0.4쪽
#:     고딕+명조 매핑     쪽수 정확 20/22 · 평균 오차 0.3쪽  ← 이것
#:
#: 대체 글꼴이 원본과 글자폭이 다르면 줄바꿈이 밀리고 쪽수가 달라진다. 쪽수가
#: 맞는다는 것은 폭이 맞았다는 뜻이라, 눈으로 고르는 것보다 이 숫자가 낫다.
#:
#: 남는 오차는 글꼴이 아니라 **조판 엔진 차이**다(표 셀 높이·행간 계산). 표가 많은
#: 문서 둘이 6쪽까지 벌어지는데, 글꼴을 아무리 맞춰도 그건 안 좁혀진다.
_FONT_ALIASES: dict[str, tuple[str, ...]] = {
    "Noto Sans CJK KR": ("맑은 고딕", "Malgun Gothic", "굴림", "Gulim", "굴림체",
                         "GulimChe", "돋움", "Dotum", "돋움체", "DotumChe",
                         "HY헤드라인M", "나눔바른고딕OTF"),
    "Noto Serif CJK KR": ("바탕", "Batang", "바탕체", "BatangChe", "궁서", "Gungsuh",
                          "AdobeMyungjoStd-Medium"),
}


def fontconfig_xml() -> str:
    """없는 글꼴을 대신할 규칙. **alias/prefer 를 쓴다 — assign/strong 이 아니다.**

    `binding="strong"` 으로 갈아끼우면 **진짜 맑은 고딕이 깔려 있어도** Noto 로
    덮어버린다(실측으로 확인했다). alias/prefer 는 요청한 글꼴을 앞에 두고 우리
    것을 뒤에 붙이므로, 진짜가 있으면 진짜가 이기고 없을 때만 대체가 걸린다.

    Noto 가 안 깔린 서버에서는 규칙이 아무것도 못 찾아 지금과 똑같이 동작한다.
    """
    aliases = "".join(
        f"<alias><family>{_html.escape(name)}</family>"
        f"<prefer><family>{_html.escape(target)}</family></prefer></alias>"
        for target, names in _FONT_ALIASES.items() for name in names)
    return ('<?xml version="1.0"?>'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
            # 시스템 설정을 그대로 물려받는다. 빼면 글꼴 경로를 잃어 아무것도 못 찾는다.
            '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
            + aliases + "</fontconfig>")


def _font_env(work: Path) -> dict[str, str]:
    """soffice 에 줄 환경. 글꼴 규칙을 **이 프로세스에만** 먹인다.

    시스템 /etc/fonts 를 건드리지 않으므로 sudo 가 필요 없고, 서버의 다른 프로그램에
    영향이 없다. 파일을 못 쓰면 규칙 없이 간다 — 변환 자체를 막지는 않는다.
    """
    env = dict(os.environ)
    try:
        conf = work / "fonts.conf"
        conf.write_text(fontconfig_xml(), encoding="utf-8")
    except OSError:
        return env
    env["FONTCONFIG_FILE"] = str(conf)
    return env


def build_html(text: str) -> str:
    """마크다운형 추출 텍스트 → HTML. 세 규칙만 — 미리보기 렌더러와 같다.

    1) `#`~`####` 제목  2) 연속 `| a | b |` → 하나의 <table>  3) 그 외 줄 → <p>
    """
    lines = text.split("\n")
    body: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#"):
            lvl = min(len(ln) - len(ln.lstrip("#")), 4)
            body.append(f"<h{lvl}>{_html.escape(ln.lstrip('# ').strip())}</h{lvl}>")
            i += 1
        elif ln.strip().startswith("|"):
            rows: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(
                    "<tr>" + "".join(
                        f"<td>{_html.escape(c)}</td>" for c in cells) + "</tr>")
                i += 1
            body.append("<table>" + "".join(rows) + "</table>")
        else:
            if ln.strip():
                body.append(f"<p>{_html.escape(ln)}</p>")
            i += 1
    return (
        '<html><head><meta charset="utf-8"><style>'
        'body{font-family:"NanumGothic";font-size:10pt;line-height:1.4}'
        "table{border-collapse:collapse;width:100%;margin:6px 0}"
        "td{border:1px solid #666;padding:3px}"
        "h1,h2,h3,h4{font-family:\"NanumGothic\";margin:10px 0 4px}"
        "</style></head><body>" + "".join(body) + "</body></html>"
    )


def _run_soffice(cmd: list[str], work: Path) -> subprocess.CompletedProcess:
    """soffice 를 **자기 프로세스 그룹**에서 돌리고, 시한을 넘기면 그룹째 죽인다.

    `subprocess.run(timeout=…)` 만으로는 못 죽인다. `/usr/bin/soffice` 는 껍데기고
    진짜 일은 그 아래 `soffice.bin` 이 하는데, timeout 은 **직접 자식**만 죽이므로
    soffice.bin 이 고아로 남아 영원히 돈다.

    실측(2026-08-21): 그렇게 남은 soffice.bin 하나가 **22일**을 돌고 있었다. 그
    검토 스레드는 끝나지 못했고, 서버의 임시 폴더 청소가 그 스레드를 기다리는
    구조라(app/server.py) 업로드 원본 문서까지 22일간 /tmp 에 남아 있었다.
    한 프로세스를 못 죽인 것이 사내 문서를 22일 방치로 이어지게 했다.

    start_new_session 으로 새 세션·프로세스 그룹을 만들고, 시한이 지나면
    killpg 로 그 그룹 전체를 죽인다 — soffice.bin 도 같은 그룹에 있다.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=_font_env(work), start_new_session=True)
    try:
        out, err = proc.communicate(timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()                    # 그룹을 못 잡으면 자식만이라도
        proc.communicate()                 # 파이프를 비워 좀비를 안 남긴다
        raise ConvertTimeout(
            f"문서 변환이 {_TIMEOUT}초 안에 안 끝나 중단했습니다. "
            "문서가 매우 크거나 LibreOffice 가 물렸을 수 있습니다.") from None
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _soffice_to_pdf(src: Path, work: Path) -> bytes:
    """src(docx 또는 html)를 work 안에서 PDF로 변환하고 바이트를 돌려준다."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise ConvertUnavailable(
            "문서 변환에는 LibreOffice가 필요합니다. 설치: sudo apt install libreoffice")
    # 프로파일을 격리한다 — 동시 호출이 같은 프로파일을 다투면 한쪽이 조용히 실패한다.
    # 그것만으로는 부족해 락으로 한 번에 하나만 돌린다(_SOFFICE_LOCK 주석 참고).
    profile = (work / "lo").as_uri()
    with _SOFFICE_LOCK:
        done = _run_soffice(
            [exe, "--headless", f"-env:UserInstallation={profile}",
             "--convert-to", "pdf", "--outdir", str(work), str(src)], work)

    # **반환코드가 아니라 산출물을 본다.** soffice 는 변환을 다 끝내고 종료할 때
    # segfault(139) 하는 일이 잦다 — 실측으로 같은 hwpx 를 네 번 변환했더니 두 번이
    # 139 였는데, 그 PDF 는 성공한 것과 크기·쪽수·그림수·%%EOF 까지 똑같았다.
    # check=True 로 반환코드만 보던 옛 코드는 그 멀쩡한 PDF 를 버리고 hwpx 를 텍스트
    # 재현본으로 폴백했다 — 사용자는 절반의 확률로 원본이 아닌 문서를 보면서 그
    # 사실을 몰랐다. hwp 는 폴백이 없어 아예 "변환 실패"가 됐다.
    out = work / (src.stem + ".pdf")
    data = out.read_bytes() if out.exists() else b""
    # 잘린 파일을 통과시키지 않는다. 변환 도중에 죽었으면 %%EOF 가 없다.
    if data[:4] == b"%PDF" and b"%%EOF" in data[-2048:]:
        return data

    raise _SofficeFailed(
        done.returncode,
        f"LibreOffice가 온전한 PDF를 내지 못했습니다 (종료코드 {done.returncode}"
        f"{', 산출물 없음' if not data else f', {len(data)}바이트'}).")


def _hwp_failure(exc: Exception) -> str:
    """hwp 변환 실패 사유. 크래시를 "확장 없음"으로 오진하지 않는다.

    옛 메시지는 무슨 이유든 "H2Orestart 를 설치하세요"였다. 그런데 실제로 본 실패는
    확장이 멀쩡히 설치된 상태에서 soffice 가 **segfault(139)** 한 것이었고, 그 메시지
    때문에 원인을 세 번이나 놓쳤다. 설치 안내는 실행 자체가 실패했을 때만 맞다.
    """
    code = getattr(exc, "returncode", None)
    if code is not None and code < 0 or code == 139:
        # 음수는 파이썬이 시그널을 그렇게 표현한 것이고, 139 는 셸의 128+11 표기다.
        return ("hwp 변환 중 LibreOffice 가 비정상 종료했습니다"
                f" (종료코드 {code}). 같은 문서를 다시 시도해 보세요 — 동시 변환이"
                " 겹치면 죽는 일이 있습니다.")
    return ("hwp 변환에는 H2Orestart LibreOffice 확장이 필요합니다. "
            "설치: sudo unopkg add --shared H2Orestart.oxt"
            + (f" (종료코드 {code})" if code is not None else ""))


def to_pdf(path: Path) -> bytes:
    """포맷 → PDF 바이트.

    docx/hwp/hwpx: LibreOffice 직접 변환(hwp/hwpx는 H2Orestart 필터). pdf: 통과.
    H2Orestart 가 없으면 hwpx 는 추출 텍스트 재현본으로 폴백하고, hwp 는 설치를 안내한다.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="docreview-conv-") as tmp:
        work = Path(tmp)
        if ext == ".docx":
            # w:ptab(절대위치 탭)을 LibreOffice 가 읽는 탭으로 바꾼 사본을 변환한다.
            # 안 바꾸면 머릿말의 `의뢰번호 … 성적서번호` 가 붙어 나온다(ptab.py).
            # 바꿀 것이 없으면 원본을 그대로 복사하므로 옛 문서에도 안전하다.
            staged = work / f"ptab-{path.name}"
            try:
                rewrite_ptabs(path, staged)
            except (OSError, zipfile.BadZipFile):
                staged = path      # 사본을 못 만들면 원본으로 간다. 변환을 막지 않는다.
            return _soffice_to_pdf(staged, work)
        if ext == ".hwp":
            try:
                return _soffice_to_pdf(path, work)          # H2Orestart 필터
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                raise ConvertUnavailable(_hwp_failure(exc)) from exc
        if ext == ".hwpx":
            try:
                return _soffice_to_pdf(path, work)          # H2Orestart 직접 변환(진짜 레이아웃)
            except (subprocess.CalledProcessError, RuntimeError):
                # 확장이 없으면 추출 텍스트로 재현본을 만든다(원본 레이아웃은 아니다).
                text = load_document(path).text
                src = work / "recon.html"
                src.write_text(build_html(text), encoding="utf-8")
                return _soffice_to_pdf(src, work)
    raise UnsupportedFormatError(f"PDF로 변환할 수 없는 형식: {ext}")
