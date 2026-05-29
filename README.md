# ACCELA Compatible Linux

Versão modificada em pt-BR do ACCELA, adaptada para Linux e mantida neste repositório.

Build do ACCELA preparada para Linux com:

- interface em pt-BR
- modo stealth com bandeja do sistema e autostart
- fechamento automático quando a Steam fecha
- OpenCloudSave com `rclone`
- Rich Presence opcional do ACCELA
- instalador automático de dependências e do `SLSsteam`
- atualizações pelo GitHub dentro do próprio app

## Agradecimento

Agradecimento discreto ao portal oficial do ACCELA Dist Archive pelo projeto open source:
`https://portal3d.github.io/accela-dist-archive/`

## Licença

Este repositório preserva a base open source do projeto original sob licença `MIT`.
O aviso de licença e copyright do upstream foi mantido no arquivo `LICENSE`.

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

## Fluxo de desenvolvimento

Dentro do repositório existem dois atalhos:

```bash
bash dev-install.sh
```

Reinstala a versão atual do repositório em `~/.local/share/ACCELA` para testar localmente.

```bash
bash publish-update.sh "mensagem do commit"
```

Faz `git add`, `git commit` e `git push` para o `main`.

## Atualizações

O ACCELA verifica o branch `main` deste repositório e pode:

- avisar quando sair commit novo
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

Demonstration: 

<video src="https://github.com/user-attachments/assets/67e7de40-be6f-4258-b9f4-ba48ab4f09b1" width="100%" controls></video>
