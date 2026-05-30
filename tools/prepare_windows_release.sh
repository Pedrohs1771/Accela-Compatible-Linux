#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
INPUT_ZIP="${1:-}"
DIST_DIR="$ROOT_DIR/dist"
WORK_DIR="${TMPDIR:-/tmp}/accela-windows-release.$$"
OUTPUT_NAME="ACCELA-Windows-x64.zip"
OUTPUT_PATH="$DIST_DIR/$OUTPUT_NAME"
SHA_PATH="$DIST_DIR/$OUTPUT_NAME.sha256"

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

if [ -z "$INPUT_ZIP" ]; then
    echo "Uso: bash tools/prepare_windows_release.sh /caminho/ACCELA-windows-binary.zip" >&2
    exit 1
fi

if [ ! -f "$INPUT_ZIP" ]; then
    echo "Arquivo não encontrado: $INPUT_ZIP" >&2
    exit 1
fi

mkdir -p "$DIST_DIR" "$WORK_DIR"
unzip -q "$INPUT_ZIP" -d "$WORK_DIR/unpacked"

SOURCE_DIR="$(find "$WORK_DIR/unpacked" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -z "$SOURCE_DIR" ]; then
    echo "O ZIP não contém uma pasta raiz válida." >&2
    exit 1
fi

for required in ACCELA.exe vc_redist.x64.exe vc_redist.x86.exe; do
    if [ ! -f "$SOURCE_DIR/$required" ]; then
        echo "Pacote Windows incompleto: faltando $required" >&2
        exit 1
    fi
done

PACKAGE_DIR="$WORK_DIR/package/ACCELA-Windows-x64"
mkdir -p "$PACKAGE_DIR"
cp "$SOURCE_DIR/ACCELA.exe" "$PACKAGE_DIR/"
cp "$SOURCE_DIR/vc_redist.x64.exe" "$PACKAGE_DIR/"
cp "$SOURCE_DIR/vc_redist.x86.exe" "$PACKAGE_DIR/"
cp "$ROOT_DIR/windows/Apply-AccelaPreset.ps1" "$PACKAGE_DIR/"
cp "$ROOT_DIR/windows/Launch-ACCELA.cmd" "$PACKAGE_DIR/"

cat > "$PACKAGE_DIR/README_WINDOWS_PTBR.txt" <<'TXT'
ACCELA Windows x64

Arquivos:
- ACCELA.exe
- vc_redist.x64.exe
- vc_redist.x86.exe
- Launch-ACCELA.cmd
- Apply-AccelaPreset.ps1

Instalação recomendada:
1. Se o Windows pedir runtime, execute vc_redist.x64.exe.
2. Em sistemas/launchers antigos, instale também vc_redist.x86.exe.
3. Abra Launch-ACCELA.cmd para aplicar o preset do ACCELA sem sobrescrever suas chaves.
4. Depois disso, você também pode abrir ACCELA.exe normalmente.

Observações:
- Este pacote é a build Windows distribuída junto do repositório universal do ACCELA.
- O launcher aplica apenas defaults ausentes no registro do usuário.
- O preset aponta updates para Pedrohs1771/Accela-Compatible-Linux e desliga o áudio por padrão.
TXT

(
    cd "$WORK_DIR/package"
    rm -f "$OUTPUT_PATH"
    zip -qr "$OUTPUT_PATH" "ACCELA-Windows-x64"
)

sha256sum "$OUTPUT_PATH" | awk '{print $1}' > "$SHA_PATH"
echo "Pacote Windows gerado: $OUTPUT_PATH"
echo "SHA256 salvo em: $SHA_PATH"
