# ACCELA Windows

Pacote Windows x64 distribuído junto do repositório principal.

## Conteúdo esperado

- `ACCELA.exe`
- `vc_redist.x64.exe`
- `vc_redist.x86.exe`
- `Launch-ACCELA.cmd`
- `Apply-AccelaPreset.ps1`

## Fluxo recomendado

1. Baixe `ACCELA-Windows-x64.zip` na release.
2. Extraia para uma pasta fixa.
3. Se o Windows pedir runtime, rode `vc_redist.x64.exe`.
4. Abra `Launch-ACCELA.cmd`.
5. Depois do primeiro launch, `ACCELA.exe` também já pode ser usado direto.

## O que o launcher faz

- aplica só as configurações ausentes em `HKCU\Software\Tachibana Labs\ACCELA`
- aponta o updater para `Pedrohs1771/Accela-Compatible-Linux`
- liga checagem de update
- mantém assinatura obrigatória
- deixa o Rich Presence habilitado por padrão
- desliga o áudio por padrão
- não mexe nas keys do usuário se elas já existirem

## Objetivo desta pasta

Esta área documenta a distribuição Windows e mantém o repositório pronto para publicar as duas plataformas:

- `ACCELA-Universal-latest.zip` para Linux
- `ACCELA-Windows-x64.zip` para Windows

## Empacotamento

Para gerar o artefato normalizado a partir de uma build Windows existente:

```bash
bash tools/prepare_windows_release.sh /caminho/ACCELA-windows-binary.zip
```
