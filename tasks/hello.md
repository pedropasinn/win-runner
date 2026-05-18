<!-- workspace: %USERPROFILE%\repo\win-runner -->
# Fila: hello — smoke test do win-runner

Fila mínima para validar a instalação. Se todas as tarefas terminam com
`[x]`, o pipeline está funcional.

## Bloco: smoke

- [ ] (model=haiku) responda apenas com a frase: "win-runner OK"
- [ ] (model=haiku, verify="echo hello") imprima uma saudação curta
- [ ] (model=sonnet) explique em 1 frase o que é um arquivo .md de fila do win-runner

## Bloco: depends

- [ ] (id=passo_um, model=haiku) diga "passo um"
- [ ] (depends=passo_um, model=haiku) diga "passo dois — só depois do um"

## Bloco: router_auto

- [ ] (model=auto) renomeie a variável foo para bar em scratch.py (deve cair em haiku)
- [ ] (model=auto) refatore o módulo auth para arquitetura hexagonal (deve cair em opus)
- [ ] (model=auto) adicione tratamento de erro no endpoint /users (deve cair em sonnet)

## Bloco: memory

- [ ] (model=sonnet, memory=queue) escreva uma frase: "primeiro passo"
- [ ] (model=sonnet, memory=queue) continue a partir do que disse acima — descreva o próximo passo

## Bloco: multiprovider

- [ ] (model=gemini:flash) diga "olá do Gemini"
- [ ] (model=haiku, escalate=gemini:pro) diga "se o haiku falhar, peça pro gemini-pro"
