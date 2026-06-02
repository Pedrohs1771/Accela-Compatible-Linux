# AUDIT

## Estado atual

- A base Linux segue funcional e continua sendo a referência principal.
- O projeto já tinha muita lógica de Windows espalhada em `game_manager`, `task_manager`, `steam_helpers`, `helpers` e `main.py`.
- O binário histórico `ACCELA.exe` foi extraído com sucesso e serviu como referência para confirmar o stack usado no Windows.

## O que o binário Windows antigo confirma

- Empacotamento PyInstaller.
- Dependências principais: `SteamKit2.dll`, `DepotDownloader.dll`, `Steamless`, `ACCELA.reg`, `ACCELA_uninstall.reg`.
- Fluxos específicos de Windows: registro, `steam.exe`, `appinfo.vdf`, bibliotecas Steam e DLL/launcher próprios.
- `SLSsteam` não aparece como runtime principal de Windows; ele continua sendo integração Linux.

## Riscos encontrados antes do port

- Updater antigo misturava pasta de dados e pasta de instalação no Windows.
- Fallback para ZIP do código-fonte não era seguro para runtime Windows.
- UI ainda expunha SLSsteam como se fosse ferramenta universal.
- O repo padrão do updater ainda apontava para slugs antigos.

## Correções estruturais desta rodada

- Separação explícita entre `get_base_path()` e `get_install_root()`.
- Updater preparado para selecionar pacote por plataforma e bloquear fallback Linux no Windows.
- Autostart e protocolo Windows agora usam launcher nativo da plataforma.
- Templates `.reg` adicionados ao projeto.
- Scripts dedicados para build e instalação do bundle Windows.

## Próximos passos

- Concluir manifesto multi-plataforma em `release/latest.json`.
- Fechar pipeline de release Linux + Windows.
- Validar o bundle Windows em runner real ou máquina Windows antes de publicar como estável.
