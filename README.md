# ACCELA Compatible Linux

Build do ACCELA preparada para Arch Linux com:

- interface em pt-BR
- modo stealth com bandeja do sistema e autostart
- fechamento automático quando a Steam fecha
- OpenCloudSave com `rclone`
- Rich Presence opcional do ACCELA
- instalador automático de dependências e do `SLSsteam`
- atualizações pelo GitHub dentro do próprio app

## Instalação

```bash
git clone https://github.com/Pedrohs1771/Accela-Compatible-Linux.git
cd Accela-Compatible-Linux
bash install.sh
```

O instalador:

- copia o ACCELA para `~/.local/share/ACCELA`
- cria os launchers em `~/.local/bin`
- gera os atalhos de desktop
- monta a `.venv` local do app
- instala as dependências Python do bundle
- baixa e instala a versão oficial mais recente do `SLSsteam`
- tenta instalar os pacotes de sistema necessários no Arch

## Uso

Depois da instalação:

```bash
accela
```

O instalador também cria aliases com várias capitalizações de `accela`.

## Atualizações

O ACCELA verifica tags/releases deste repositório e pode:

- avisar quando sair uma versão nova
- instalar a atualização automaticamente
- aplicar o update direto pela aba `Updates`

## Chaves de API

As chaves não vão no repositório nem no pacote. Cada pessoa precisa adicionar as próprias em:

- Hubcap
- SteamGridDB
- Discord Rich Presence
- OpenCloudSave / `rclone`

## Observações

- O Rich Presence do Discord precisa de um `Client ID` e assets de imagem válidos na aplicação do Discord.
- O app já inclui `rclone`, `DepotDownloader`, `Steamless`, `Goldberg` e o material do `SLScheevo`.
- O instalador é focado em Arch Linux. Em outras distros ele ainda copia o app, mas a instalação automática de pacotes pode não acontecer.
