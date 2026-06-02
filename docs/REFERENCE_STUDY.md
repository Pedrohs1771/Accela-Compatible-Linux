# REFERENCE STUDY

## Referências usadas

### ACCELA.exe Windows

Usado apenas como referência técnica para:

- stack de empacotamento no Windows
- dependências embutidas
- fluxo de launcher/registro
- artefatos de update e integração com Steam

### O que foi reaproveitado como conceito

- uso de templates `.reg` para protocolo e contexto de ZIP
- organização de dependências Windows dedicadas
- separação entre runtime e artefatos de instalação

### O que foi evitado

- copiar o binário legado
- misturar `SLSsteam`/`LD_AUDIT` no runtime Windows
- depender de `AppRun`, `.desktop` ou instalador Linux no port de Windows

## Resultado

O port passa a tratar Windows como destino próprio:

- launcher `.cmd` / PowerShell
- bundle com `.venv` no Windows
- updater preparado para pacote Windows
- autostart no Startup folder
- registro do protocolo `lumatools://`
