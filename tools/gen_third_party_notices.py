"""同梱するサードパーティ製ソフトウェアの一覧（THIRD-PARTY-NOTICES.md）を生成する。

手で書くと必ず古くなる。実際に配布物へ入るパッケージの `*.dist-info` を読んで作る。

    # 本体だけ（今の Python 環境にインストールされているもの）
    python tools/gen_third_party_notices.py --out THIRD-PARTY-NOTICES.md

    # 採譜アドオンも含める（ビルド済みのエンジンフォルダを渡す）
    python tools/gen_third_party_notices.py \
        --addon D:/omr_build/omr --addon D:/pitch_build/pitch \
        --out THIRD-PARTY-NOTICES.md

**コピーレフト（GPL / LGPL / MPL）は検出して一覧に出す。**
無料配布なら誰も気にしないが、お金を取った瞬間に性質が変わる。LGPL / MPL のライブラリは
同梱してよいが、(1) ライセンス全文を配布物に含めること、(2) 利用者が差し替えられる形
（Python パッケージとして import される＝動的リンク）であることが要る。

**全文が同梱されていないコピーレフトのパッケージがあれば終了コード 1 を返す。** そこが
実際の違反になる。ライセンス名を検出しただけでは失敗させない（それは正常な状態だから）。
"""

from __future__ import annotations

import argparse
import email.parser
import os
import re
import sys

# 本体が必ず使うもの（requirements.txt に対応）。名前は dist-info の正規化前。
_MAIN_PACKAGES = ["customtkinter", "pillow", "pypdfium2", "mido", "darkdetect", "packaging"]

# 注意して扱うライセンス。同梱してよいが、告知と条件の確認が要る。
_COPYLEFT = re.compile(r"\b(GPL|LGPL|AGPL|MPL|EPL|CDDL)\b", re.IGNORECASE)
# 上の正規表現に引っかかるが、実際にはコピーレフトではないもの
_NOT_COPYLEFT = re.compile(r"GPL-compatible|LGPL-compatible", re.IGNORECASE)


def log(message: str) -> None:
    # Windows のコンソールは cp932 のことがある。絵文字を落として文字化けで死なせない。
    encoding = sys.stdout.encoding or "utf-8"
    safe = message.encode(encoding, errors="replace").decode(encoding)
    print(f"[notices] {safe}", flush=True)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_metadata(dist_info: str) -> dict[str, str] | None:
    path = os.path.join(dist_info, "METADATA")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        message = email.parser.Parser().parse(fh, headersonly=True)

    license_name = (message.get("License-Expression") or message.get("License") or "").strip()
    if not license_name or "\n" in license_name:
        # 古いパッケージは License にライセンス全文を入れていることがある。分類子を使う。
        classifiers = message.get_all("Classifier") or []
        licenses = [c.split("::")[-1].strip() for c in classifiers if c.startswith("License ::")]
        license_name = " / ".join(licenses) if licenses else "（METADATA に記載なし）"

    return {
        "name": message.get("Name", os.path.basename(dist_info)),
        "version": message.get("Version", "?"),
        "license": license_name,
        "url": message.get("Home-page") or _project_url(message) or "",
    }


def _project_url(message) -> str:
    for entry in message.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in ("homepage", "source", "repository"):
            return url.strip()
    return ""


_LICENSE_NAMES = ("LICENSE", "NOTICE", "COPYING", "AUTHORS", "THIRDPARTY")
# pypdfium2 のように、ファイル名ではなくディレクトリ名でライセンスを示す流儀がある
# （`licenses/LICENSES/Apache-2.0.txt`）。名前だけ見ていると見落とす。
_LICENSE_DIRS = {"licenses", "license", "license_files"}


def _scan_licenses(base: str, relative_to: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(base):
        parts = {p.lower() for p in os.path.relpath(root, base).split(os.sep)}
        in_license_dir = bool(parts & _LICENSE_DIRS)
        for name in files:
            if in_license_dir or name.upper().startswith(_LICENSE_NAMES):
                found.append(os.path.relpath(os.path.join(root, name), relative_to))
    return found


def _license_files(dist_info: str, site_packages: str) -> list[str]:
    """ライセンス全文の在処。dist-info だけでなくパッケージ本体も見る。

    onnxruntime のように `onnxruntime/LICENSE` へ置くパッケージがある。dist-info しか
    見ないと「同梱なし」と誤判定し、実際には満たしている義務を違反と報告してしまう。
    """
    found = _scan_licenses(dist_info, site_packages)
    for top in _top_level_dirs(dist_info):
        package_dir = os.path.join(site_packages, top)
        if os.path.isdir(package_dir):
            found += _scan_licenses(package_dir, site_packages)
    return sorted(set(found))


def _top_level_dirs(dist_info: str) -> list[str]:
    path = os.path.join(dist_info, "top_level.txt")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return [line.strip() for line in fh if line.strip()]
    # top_level.txt が無いパッケージは dist-info 名から推測する
    return [os.path.basename(dist_info).split("-")[0]]


def _site_packages(root: str) -> str | None:
    for candidate in (
        os.path.join(root, "python", "Lib", "site-packages"),
        os.path.join(root, "Lib", "site-packages"),
        root,
    ):
        if os.path.isdir(candidate) and any(
            d.endswith(".dist-info") for d in os.listdir(candidate)
        ):
            return candidate
    return None


def _fallback_license(name: str, extra_dir: str | None) -> str | None:
    """wheel がライセンス全文を同梱していないパッケージのために、こちらで用意した全文。

    flatbuffers のように、Apache-2.0 なのに wheel へ LICENSE を入れていないものがある。
    再配布の条件はライセンス文の同梱なので、無ければこちらで添付するしかない。
    """
    if not extra_dir or not os.path.isdir(extra_dir):
        return None
    prefix = _normalize(name) + "-"
    for entry in sorted(os.listdir(extra_dir)):
        if _normalize(entry).startswith(prefix):
            return f"{os.path.basename(extra_dir)}/{entry}"
    return None


def _collect(
    site_packages: str, only: list[str] | None = None, extra_dir: str | None = None
) -> list[dict[str, str]]:
    wanted = {_normalize(n) for n in only} if only else None
    packages: list[dict[str, str]] = []
    for entry in sorted(os.listdir(site_packages)):
        if not entry.endswith(".dist-info"):
            continue
        dist_info = os.path.join(site_packages, entry)
        meta = _read_metadata(dist_info)
        if meta is None:
            continue
        if wanted is not None and _normalize(meta["name"]) not in wanted:
            continue
        found = _license_files(dist_info, site_packages)
        if not found:
            fallback = _fallback_license(meta["name"], extra_dir)
            found = [fallback] if fallback else []
        meta["license_files"] = ", ".join(found) or "（同梱なし）"
        packages.append(meta)
    return packages


def _is_copyleft(license_name: str) -> bool:
    if _NOT_COPYLEFT.search(license_name):
        return False
    return bool(_COPYLEFT.search(license_name))


def _table(packages: list[dict[str, str]]) -> list[str]:
    lines = ["| パッケージ | バージョン | ライセンス | ライセンス全文 |", "|---|---|---|---|"]
    for pkg in sorted(packages, key=lambda p: _normalize(p["name"])):
        mark = " ⚠️" if _is_copyleft(pkg["license"]) else ""
        lines.append(
            f"| [{pkg['name']}]({pkg['url']}) | {pkg['version']} | "
            f"{pkg['license']}{mark} | {pkg['license_files']} |"
            if pkg["url"] else
            f"| {pkg['name']} | {pkg['version']} | {pkg['license']}{mark} | {pkg['license_files']} |"
        )
    return lines


def build(args: argparse.Namespace) -> int:
    sections: list[tuple[str, str, list[dict[str, str]]]] = []

    main_site = _here_site() or _site_packages(os.path.dirname(sys.executable))
    if main_site:
        log(f"本体の依存を {main_site} から収集")
        sections.append(("本体（AutoPlayNotes.exe）", main_site,
                         _collect(main_site, _MAIN_PACKAGES, args.licenses)))
    else:
        log("警告: 本体の site-packages が見つかりません")

    for addon in args.addon or []:
        site = _site_packages(os.path.abspath(addon))
        if site is None:
            raise SystemExit(f"site-packages が見つかりません: {addon}")
        name = os.path.basename(os.path.abspath(addon).rstrip("/\\"))
        log(f"アドオン {name}/ の依存を収集")
        sections.append((f"採譜アドオン: {name}/", site, _collect(site, extra_dir=args.licenses)))

    out: list[str] = [
        "# サードパーティ製ソフトウェアの表示",
        "",
        "AutoPlayNotes は以下のオープンソースソフトウェアを同梱・利用しています。",
        "各ライセンスの全文は、配布物の中の該当ファイル（下表「ライセンス全文」列）に含まれています。",
        "",
        "> このファイルは `tools/gen_third_party_notices.py` が生成します。手で編集しないでください。",
        "",
    ]

    copyleft: list[tuple[str, dict[str, str]]] = []
    for title, site, packages in sections:
        out += [f"## {title}", "", f"{len(packages)} パッケージ", ""]
        out += _table(packages)
        out += [""]
        copyleft += [(title, p) for p in packages if _is_copyleft(p["license"])]

    if copyleft:
        out += [
            "## コピーレフト系ライセンスのパッケージ",
            "",
            "以下は GPL 系 / MPL のライセンスです（上表で ⚠️ を付けたもの）。",
            "いずれも**改変せずそのまま同梱**しており、**ライセンス全文を配布物に含めています**。",
            "また Python のパッケージとして実行時に `import` される（動的リンク）ため、",
            "利用者が同じ名前の自前ビルドに**差し替えることができます**。",
            "",
        ]
        for title, pkg in copyleft:
            out.append(
                f"- **{pkg['name']} {pkg['version']}** — {pkg['license']} "
                f"（{title}／全文: `{pkg['license_files']}`）"
            )
        out.append("")

    out += [
        "## Python 本体",
        "",
        "採譜アドオンには CPython の埋め込み版を同梱しています（`<エンジン>/python/`）。",
        "ライセンスは PSF License Agreement（`python/LICENSE.txt`）です。",
        "",
        "## 学習済みモデル",
        "",
        "- oemer の五線譜認識モデル（`unet_big` / `seg_net`）: oemer 本体と同じ MIT License。",
        "- basic-pitch の採譜モデル: basic-pitch 本体と同じ Apache License 2.0。",
        "",
        "## 商標",
        "",
        "本文中のゲーム名・製品名は各社の商標です。AutoPlayNotes はそれらと提携していません。",
        "",
    ]

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    log(f"書き出し: {args.out}  （{sum(len(p) for _t, _s, p in sections)} パッケージ）")

    if copyleft:
        log("")
        log("[i] コピーレフト系のライセンス（同梱可・全文の同梱が必須）:")
        for title, pkg in copyleft:
            log(f"   {title}: {pkg['name']} {pkg['version']} - {pkg['license']}")

    # 実際の違反はここ。MIT も BSD も Apache も「ライセンス文の同梱」が再配布の条件。
    # ライセンス名を検出しただけでは失敗させない（それは正常な状態）。
    missing = [
        (title, pkg) for title, _site, packages in sections for pkg in packages
        if pkg["license_files"] == "（同梱なし）"
    ]
    if missing:
        log("")
        log("[!] ライセンス全文が配布物に入っていません。有償配布の前に必ず解決してください:")
        for title, pkg in missing:
            log(f"   {title}: {pkg['name']} {pkg['version']} - {pkg['license']}")
        return 1
    return 0


def _here_site() -> str | None:
    import site

    for path in site.getsitepackages():
        if os.path.isdir(path) and any(d.endswith(".dist-info") for d in os.listdir(path)):
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="THIRD-PARTY-NOTICES.md を生成する")
    parser.add_argument("--addon", action="append", help="採譜アドオンのフォルダ（複数可）")
    parser.add_argument("--licenses", default="licenses",
                        help="wheel が全文を同梱していない場合の補完ディレクトリ")
    parser.add_argument("--out", default="THIRD-PARTY-NOTICES.md")
    return build(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
