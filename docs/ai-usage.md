# Uso de Inteligência Artificial

> **⚠️ NOTA IMPORTANTE:** Este documento reflete o uso real de ferramentas de IA (assistentes virtuais baseados em LLM) durante o desenvolvimento e depuração da arquitetura distribuída do Sistema de Matrículas.

---

## 1. Ferramentas de IA Utilizadas

| Ferramenta | Versão/Modelo | Finalidade Principal |
|------------|---------------|----------------------|
| *Gemini Assistant (Antigravity)* | *Gemini / Google DeepMind* | *Resolução de bugs complexos, desenvolvimento de resiliência (Circuit Breaker), ajustes de infraestrutura Docker e documentação.* |

---

## 2. Onde as Ferramentas Foram Utilizadas

### 2.1 Arquitetura e Design

- [x] Definição da arquitetura do sistema
- [x] Escolha de padrões de comunicação (síncrono/assíncrono)
- [x] Design dos contratos de API
- [x] Estratégia de tolerância a falhas

**Detalhes:**
A IA foi utilizada para estruturar a topologia da rede no Docker Compose, validando a integração entre a comunicação síncrona (REST) e assíncrona (RabbitMQ), garantindo que a proposta arquitetural atendesse aos requisitos obrigatórios do trabalho.

### 2.2 Implementação de Código

- [x] Middleware API (gateway, autenticação, resiliência)
- [x] Course Service
- [x] Enrollment Service
- [x] Notification Worker
- [x] Configuração do Docker Compose

**Detalhes:**
A IA gerou e refinou a lógica de resiliência no `middleware/app.py`, especificamente o Wrapper de requisições `resilient_request` com suporte a Timeout, Exponential Backoff Retry e Circuit Breaker. Também auxiliou no alinhamento das variáveis de ambiente no Docker Compose.

### 2.3 Testes e Debugging

- [ ] Identificação de bugs
- [ ] Escrita de testes
- [x] Testes de tolerância a falhas
- [x] Validação dos contratos de API

**Detalhes:**
O uso mais intensivo da IA ocorreu na depuração (debugging) de problemas reais que surgiram:
1. Resolução de um **deadlock** causado pelo uso re-entrante de um `threading.Lock()` no endpoint do Prometheus.
2. Identificação de divergência nas chaves secretas do JWT (`JWT_SECRET`) entre o Auth Service e o Middleware.
3. Correção de um erro `AttributeError` quando o middleware recebia uma lista em vez de um dicionário na listagem de cursos.

### 2.4 Documentação

- [x] Geração de documentação técnica
- [ ] Diagramas e fluxogramas
- [x] README do projeto
- [x] Comentários no código

**Detalhes:**
A IA gerou um guia prático de apresentação (`guia_apresentacao.md`) detalhando como demonstrar cada aspecto do trabalho e adaptou comandos `curl` da documentação de Linux (bash) para Windows (CMD), permitindo a correta execução dos testes pelo grupo.

---

## 3. Principais Prompts Utilizados

### Prompt 1

**Ferramenta:** *Gemini Assistant*
**Contexto:** *Investigação de falha silenciosa onde os containers subiam mas o health check não finalizava e o endpoint ficava carregando infinitamente.*

**Prompt:**
> *"o container do Docker não responde como Healthy, ele fica carregando infinitamente. rodei novamente, e o problema continuou o mesmo"*

**Resultado:** A IA analisou os logs do Docker e o código do `app.py`, identificando um erro clássico de concorrência: um **Deadlock** no endpoint `/metrics` causado pela tentativa de adquirir um lock que já estava em uso pela mesma thread no método de cálculo de média de latência. A IA reescreveu a função retirando a chamada conflitante e resolvendo o congelamento instantaneamente.

---

### Prompt 2

**Ferramenta:** *Gemini Assistant*
**Contexto:** *Dificuldade para executar os comandos de teste da API no ambiente Windows.*

**Prompt:**
> *"Internal Server Errorcurl: (3) URL rejected: Bad hostname (...) quero esse comando pro cmd do windows"*

**Resultado:** A IA explicou a diferença no tratamento de quebra de linhas (`\` no bash vs `^` no CMD) e no escape de aspas em JSON. auxiliando na adaptação de todos os arquivos Markdown da pasta `docs/` contendo comandos `curl` para o formato de linha única suportado pelo Windows CMD.

---

### Prompt 3

**Ferramenta:** *Gemini Assistant*
**Contexto:** *Dificuldade para identificar a causa de um erro 500 (Internal Server Error) ao tentar listar os cursos através do middleware, mesmo com todos os containers rodando normalmente e sem erros aparentes na compilação.*

**Prompt:**
> *"curl http://localhost:8000/v1/courses - Internal Server Error (...) O que pode estar acontecendo? Como descubro o erro?"*

**Resultado:** A IA instruiu o uso do comando `docker compose logs middleware course-service --tail 30` para rastrear o erro interno. A partir dos logs, identificou um `AttributeError: 'list' object has no attribute 'get'` na linha 495. Explicou que ocorreu uma falha de tipagem na integração: o `course-service` retornava uma lista `[]`, mas o middleware tentava acessar um dicionário usando `.get()`. Isso ajudou a compreender a importância de validar os tipos de dados que trafegam entre microsserviços diferentes.

---

## 4. Validação dos Outputs

### 4.1 Processo de Validação

| Etapa | Descrição |
|-------|-----------|
| Revisão manual | O código gerado (especialmente a resolução do deadlock e o circuit breaker) foi lido para compreender a mecânica de concorrência e falha. |
| Testes funcionais | Cada correção e comando gerado foi validado no terminal com `docker compose build` e chamadas `curl` reais para observar os retornos (ex: código HTTP 503 no fallback). |
| Comparação com documentação | O guia de apresentação gerado pela IA foi verificado contra o edital original do trabalho para garantir que cobria 100% dos requisitos. |
| Iterações | A depuração do erro de carregamento infinito exigiu múltiplas interações: primeiro verificação do JWT, versão do bcrypt, até encontrar a causa raiz nos logs (Deadlock). |

### 4.2 Modificações Realizadas

As principais modificações feitas em conjunto com a IA a partir do código original foram:
1. Adequação de tipos de retorno no Python (tratar `list` em vez de `dict`) usando `isinstance()`.
2. Fixação da versão da biblioteca `bcrypt==4.0.1` no `requirements.txt` para resolver incompatibilidade com a dependência `passlib`.
3. Unificação das variáveis de ambiente para a chave JWT_SECRET.

### 4.3 Problemas Encontrados

Erros de sintaxe ou de lógica gerados temporariamente durante o uso da IA:
1. O envio inicial de comandos `curl` formatados com `\` (padrão Unix), que resultaram em erro de "Bad hostname" ao serem colados diretamente no Windows CMD, necessitando de uma readequação completa da documentação para o ambiente de desenvolvimento local.

---

## 5. Reflexão

### 5.1 Benefícios Observados
O uso da IA como "Pair Programmer" acelerou drasticamente a fase de depuração (debugging). Erros silenciosos como Deadlocks e travamentos em chamadas de rede são historicamente difíceis de encontrar manualmente. A capacidade da IA de analisar milhares de linhas de log do Docker em segundos e apontar a linha exata no código economizou horas de investigação.

### 5.2 Limitações Observadas
A IA tem dificuldade inicial em deduzir o sistema operacional do usuário se não for explicitamente avisada, o que resultou em comandos incompatíveis com o Windows. Além disso, a correção de um erro às vezes revelava um erro seguinte (ex: resolver o Secret do JWT revelou a incompatibilidade do Bcrypt), mostrando que a IA depende de testes sequenciais reais para avançar.

### 5.3 Aprendizados
A experiência mostrou que a IA não substitui o teste funcional. Para sistemas distribuídos (microsserviços), o valor da IA não está apenas em gerar código, mas em explicar como testá-lo (como forçar a abertura do circuit breaker e ler métricas). O maior aprendizado foi entender *por que* o código da IA funciona, e não apenas copiá-lo cegamente, garantindo domínio para a apresentação técnica.
