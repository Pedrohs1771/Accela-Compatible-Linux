# Luma Tools

O **Luma Tools** e um launcher focado em biblioteca, manifests, downloads e integracao com Steam. Esta edicao mantem a interface visual do projeto e entrega instalacao simples, atualizacoes pelo GitHub e Discord Rich Presence configurado por padrao.

## Principais recursos

- Biblioteca integrada com scan automatico da Steam
- Download e fila de manifests com processamento local
- Integracao com Steam no Linux
- Port de Windows em beta
- Update Center com pacote remoto, rollback e verificacao de integridade
- Discord Rich Presence com assets oficiais e botao para o repositorio

## Instalacao Linux

1. Baixe o asset Linux da release estavel.
2. Extraia o ZIP em qualquer pasta.
3. Entre na pasta extraida.
4. Execute:

```bash
bash install.sh
```

5. Abra com:

```bash
lumatools
```

### Linux manual/portatil

Se voce nao quiser instalar no sistema:

1. Extraia o ZIP.
2. Entre na pasta extraida.
3. Rode direto:

```bash
./lumatools
```

ou

```bash
./app/LumaTools/squashfs-root/AppRun
```

## Windows Beta

O Windows ainda esta em **beta**.

### Opcao 1: pacote beta pronto

1. Baixe o asset `LumaTools-Windows-x64-built-under-wine.zip`.
2. Extraia o ZIP.
3. Entre na pasta extraida.
4. Rode `Launch-LumaTools.cmd`.

Se quiser instalar no perfil do usuario:

1. Clique com o botao direito em `install_windows.ps1`.
2. Execute com PowerShell.

Isso instala em `%LOCALAPPDATA%\\Programs\\LumaTools` e cria atalhos.

### Opcao 2: port/source beta

Se voce quiser rebuildar o bundle do Windows:

1. Baixe o asset `LumaTools-Windows-Port-Complete.zip`.
2. Extraia o ZIP.
3. No Windows, abra PowerShell na pasta.
4. Rode:

```powershell
.\build_windows.ps1
```

ou:

```powershell
python .\tools\build_windows.py
```

Depois disso, use:

```powershell
.\dist\LumaTools-Windows-x64\Launch-LumaTools.cmd
```

## Discord Rich Presence

O Rich Presence do Luma Tools vem ativado por padrao. Quando o Discord estiver aberto, o launcher publica seu estado automaticamente e inclui um botao para o repositorio oficial. Quando um jogo detectado pela biblioteca entra em execucao, o Presence do Luma Tools e ocultado para nao disputar espaco com o Presence do jogo.
