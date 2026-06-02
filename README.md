<div align="center">

# 🌙 Luma Tools

### Launcher moderno em pt-BR para Linux e Windows

Gerencie biblioteca, manifests, depots, downloads, integração Steam, updates pelo GitHub e Discord Rich Presence em uma interface simples e bonita.

<br>

![Linux](https://img.shields.io/badge/Linux-Stable-success?style=for-the-badge&logo=linux)
![Windows](https://img.shields.io/badge/Windows-Beta-blue?style=for-the-badge&logo=windows)
![Python](https://img.shields.io/badge/Python-3.10+-yellow?style=for-the-badge&logo=python)
![License](https://img.shields.io/badge/License-MIT-purple?style=for-the-badge)

<br>

## 🚀 Instalação rápida

### 🐧 Linux

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Pedrohs1771/LumaTools-Linux/main/install.sh)
```

Depois abra com:

```bash
lumatools
```

### 🪟 Windows Beta

Baixe a versão beta em:

```txt
https://github.com/Pedrohs1771/LumaTools-Linux/releases
```

Extraia o arquivo Windows e abra:

```txt
Launch-LumaTools.cmd
```

</div>

---

## ✨ Destaques

### 📦 Manifests e Depots

O Luma Tools facilita o fluxo completo de instalação e organização:

```txt
Biblioteca → Manifests → Depots → Download → Processamento → Steam
```

Com suporte a seleção de depots, organização automática e integração com a biblioteca local.

---

### 🎮 Biblioteca integrada

Detecta e organiza jogos em uma interface simples, com foco em praticidade para quem quer baixar, configurar e abrir sem ficar mexendo em pasta manualmente.

---

### 🔄 Update Center

Sistema de atualização integrado via GitHub:

- verifica novas versões;
- baixa updates;
- valida arquivos;
- mantém o app atualizado;
- prepara rollback caso algo dê errado.

---

### 🐧 Linux Stable

A versão Linux é o foco principal do projeto.

Recursos principais:

- instalador automático;
- launcher local;
- integração com Steam;
- suporte a ambiente Arch Linux e derivados;
- execução por comando `lumatools`;
- pacote portátil via release.

---

### 🪟 Windows Beta

A versão Windows está em fase beta.

Ela inclui:

- launcher `.cmd`;
- scripts PowerShell;
- estrutura portada;
- build experimental;
- suporte inicial para Windows 10 e Windows 11.

---

### 🎧 Discord Rich Presence

O Luma Tools inclui Discord Rich Presence por padrão.

Mostra o status do launcher no Discord e tenta evitar conflito quando um jogo já possui presença própria.

---

## 📥 Downloads

Também é possível baixar manualmente pela aba Releases:

```txt
https://github.com/Pedrohs1771/LumaTools-Linux/releases
```

Arquivos recomendados:

| Sistema | Arquivo |
|---|---|
| Linux | `LumaTools-Linux-x64.zip` |
| Windows Beta | `LumaTools-Windows-x64-built-under-wine.zip` |
| Windows Dev/Source | `LumaTools-Windows-Port-Complete.zip` |

---

## 🐧 Instalação manual no Linux

Baixe o pacote Linux na aba Releases, extraia e rode:

```bash
bash install.sh
```

Depois abra com:

```bash
lumatools
```

Modo portátil:

```bash
./lumatools
```

ou:

```bash
./app/LumaTools/squashfs-root/AppRun
```

---

## 🪟 Instalação manual no Windows Beta

Baixe o pacote Windows na aba Releases.

Extraia o `.zip` e execute:

```txt
Launch-LumaTools.cmd
```

Para instalar no perfil do usuário, execute com PowerShell:

```powershell
.\install_windows.ps1
```

Caminho padrão:

```txt
%LOCALAPPDATA%\Programs\LumaTools
```

---

## 🧠 Estrutura do projeto

```txt
LumaTools-Linux/
├── app/LumaTools/          # Aplicação principal
├── release/                # Pacotes e arquivos de release
├── windows/                # Port Windows Beta
├── tools/                  # Scripts auxiliares
├── tests/                  # Testes
├── docs/                   # Documentação
├── install.sh              # Instalador Linux
├── install_windows.ps1     # Instalador Windows
├── build_windows.ps1       # Build Windows
└── README.md
```

---

## 👨‍💻 Desenvolvimento

Clone o projeto:

```bash
git clone https://github.com/Pedrohs1771/LumaTools-Linux
cd LumaTools-Linux
```

Ambiente dev:

```bash
bash dev-install.sh
```

Build Windows:

```powershell
.\build_windows.ps1
```

ou:

```powershell
python .\tools\build_windows.py
```

---

## 🛠️ Recursos planejados

- Melhorador automático de compatibilidade;
- interface mais refinada;
- sistema de plugins;
- melhorias no Windows Beta;
- logs visuais dentro do app;
- auto-update com reinício automático;
- painel avançado de depots/manifests;
- integração mais profunda com Steam.

---

## 📄 Licença

Distribuído sob licença MIT.

---

<div align="center">

### 🌙 Luma Tools

Feito para deixar biblioteca, depots, manifests e Steam integration mais simples.

</div>
