<p align="right">
  <a href="./README.md">🇺🇸 Read in English</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/app/LumaTools/squashfs-root/bin/res/logo.png" alt="LumaTools Logo" width="200">
</p>

<h1 align="center">LumaTools</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Status-Experimental_Windows-orange?style=for-the-badge" alt="Status">
</p>

<p align="center">
  <strong>O canivete suíço definitivo para gerenciamento de jogos e compatibilidade Steam.</strong><br>
  Desenvolvido por <b>Pedrohs</b>.
</p>

---

## 🚀 O que é o LumaTools?

O **LumaTools** é um launcher e gerenciador de biblioteca multiplataforma projetado para oferecer controle total sobre seus jogos Steam. Ele automatiza processos complexos como download de depots, aplicação de patches de compatibilidade e emulação de funcionalidades online, garantindo que sua experiência de jogo seja fluida, seja no **Linux (Arch, SteamOS, Ubuntu)** ou no **Windows (10/11)**.

## 🌟 Funcionalidades de Elite

*   **⚡ Native Steam Engine**: Integração profunda com a Steam nativa para detecção de bibliotecas, manifests e gerenciamento de arquivos.
*   **🌐 Online-Compatible Core**: Engine integrada para habilitar funcionalidades multiplayer e cooperativas de forma automática.
*   **📦 Smart Depot Management**: Sistema inteligente para baixar e gerenciar depots específicos, otimizando o espaço em disco.
*   **🛠️ Zero-Config Goldberg Integration**: Aplicação automatizada do Goldberg Steam Emulator com geração de `steam_appid.txt` e injeção de DLLs.
*   **🔓 Steamless Auto-Unpack**: Desempacotamento automático de executáveis protegidos por SteamStub para máxima performance.
*   **🎮 Cross-Platform Mastery**: Lógica unificada que adapta o comportamento do app para as necessidades específicas de cada SO (Proton no Linux / Nativo no Windows).
*   **🏆 Achievement Generator**: Sistema de geração e gerenciamento de conquistas para sua biblioteca pessoal.

---

## 📥 Instalação Rápida (One-Liner)

### Windows (PowerShell)
Abra o PowerShell como Administrador e cole:
```powershell
iwr -useb https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/install_windows.ps1 | iex
```

### Linux (Terminal)
Abra seu terminal favorito e cole:
```bash
curl -sSL https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/install.sh | bash
```

---

## 🧠 Estrutura do Projeto

```text
LumaTools/
├── app/LumaTools/          # Core da aplicação (Python + Recursos)
├── windows/                # Binários e Launchers específicos para Windows
├── tools/                  # Scripts de Build e Automação
├── install.sh              # Instalador inteligente para Linux
├── install_windows.ps1     # Instalador inteligente para Windows
└── lumatools               # Comando global para Linux
```

---

## 🤝 Agradecimentos Especiais

Este projeto não seria possível sem a base sólida e a inspiração de projetos open source anteriores. Um agradecimento especial ao projeto **ACCELA** por disponibilizar a base que permitiu a evolução do LumaTools.

*   **Base Open Source**: [ACCELA Dist Archive](https://portal3d.github.io/accela-dist-archive/)

---

## 🛠️ Como Buildar (Windows)

Se você é um desenvolvedor e quer gerar sua própria build:

1.  Tenha o **Python 3.10+** instalado.
2.  Execute o script de build:
    ```powershell
    python tools/build_windows.py
    ```
3.  O pacote final estará disponível na pasta `dist/`.

---

<p align="center">
  Criado com ❤️ por <b>Pedrohs</b>
</p>
