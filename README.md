# Lote Pro — Prospecção Inteligente de Áreas

Plataforma de inteligência geográfica para **encontrar, qualificar e ranquear terrenos
vazios para compra**, por finalidade (condomínio de casas, galpão logístico, loteamento…),
cruzando satélite + dados vetoriais com relevo e infraestrutura do entorno.
Inspirada no know-how da AmbGEO.

## Os 3 pilares

1. **Cidade inteira** — escolha o município no autocomplete e analise TODO o
   perímetro: o sistema baixa o limite municipal exato, a malha viária completa,
   monta as quadras e detecta os vazios urbanos de toda a cidade (job em
   background com barra de progresso). O modo endereço + raio continua disponível.
2. **Sem falso-positivo de área construída** — edificações vêm por padrão da
   **Microsoft Building Footprints** (footprints por ML de imagem de satélite,
   cobertura ~50× maior que o OSM no Brasil) mescladas ao OSM, com cache local
   por tile. Filtros morfológicos: folga em torno das edificações, largura
   mínima do vazio (mata vielas/corredores), **frente para via obrigatória**
   (mata fundos de quintal) e exclusão de praças/escolas/cemitérios/água.
3. **Estudo de implantação estilo TestFit** — escolhido o terreno baldio (com a
   ficha de matrícula preenchida), abra o estudo e dimensione casas em TEMPO
   REAL: lote-padrão, recuos, via interna e orientação por sliders; o mapa
   redesenha a implantação (lotes + casas + vias + verde) e recalcula nº de
   casas, densidade e aproveitamento a cada ajuste. O estudo é salvo na ficha
   do lote e o nº de casas sai nos exports.

## 🫧 Motor de Bolhas (IA) — qual *Bolha Incrível* desenvolver

Inspirado no **Plano Incrível** da Área Incrível, o sistema vai além de "achar e
pontuar terreno": ao clicar em **Analisar bolha (IA)** num lote, a IA lê as
variáveis já medidas (área, declividade, testada, formato, infraestrutura e
acesso do entorno) + o endereço oficial e devolve, em segundos, o estudo que
hoje uma equipe monta à mão:

- **Qual bolha** da prateleira desenvolver ali (Conquista · Conforto · Detalhe ·
  Estilo · +Vida) + arquétipo (ex.: *Detalhe Santorini*, *+Vida Vila de Bem-estar*);
- **Score de aplicabilidade 0–100** do produto àquele contexto;
- a **caixa de produto**: público-alvo, faixa MCMV (2026), promessa, narrativa,
  módulos reutilizáveis, programas acopláveis (Área Segura / Arte Incrível),
  riscos e próximos passos;
- **viabilidade econômica**: faixa MCMV → teto/preço-alvo por unidade, nº de
  unidades (do Estudo de Implantação salvo), **VGV** e custo-alvo de margem;
- **bolhas alternativas** e a justificativa amarrada às variáveis.

O estudo é salvo na ficha, sai num **Dossiê imprimível (PDF)** para o comitê e
entra nos exports. No modo cidade, **🫧 Mapa de bolhas** colore os lotes pela
linha de produto recomendada (cálculo determinístico) — visão de banco de terrenos.

> **Resiliência:** a IA roda via **OpenRouter** com *fallback entre modelos*
> (`open_router_model{,2,3}`). Se nenhum modelo responder, o estudo cai para um
> ranking **determinístico** (regras de aderência), nunca quebra. Honestidade do
> método: automatiza a triagem de produto — não substitui comitê, due diligence
> nem orçamento real.

Configuração no `.env`: `open_router_key`, `open_router_model`,
`open_router_model2`, `open_router_model3`.

## Score de viabilidade por finalidade

Cada lote detectado recebe um **score 0–100 (nota A–D)** calculado por perfil de compra:

| Critério | Fonte (gratuita, sem chave) |
|---|---|
| Declividade / desnível | OpenTopoData — SRTM 30 m |
| Acesso e pavimentação | OSM (classe da via + tag `surface`) |
| Testada (frente p/ via) | Geometria lote × malha viária OSM |
| Formato do lote | Compacidade Polsby-Popper |
| Infraestrutura do entorno | OSM: escolas/mercados/saúde/ônibus ≤ 800 m (residencial) ou proximidade de rodovia (logístico) |
| Aderência à metragem-alvo | Faixa m² informada pelo usuário |

Perfis embutidos: `condominio_casas`, `galpao_logistico`, `loteamento`, `personalizado`
(pesos ajustáveis via API). Lotes **encravados** (sem frente para via) e **íngremes**
recebem flags de alerta. Critérios sem dado são renormalizados — nunca punem o lote.

## Ficha do lote (CRM de prospecção)

Cada lote tem uma **ficha editável** (matrícula, inscrição imobiliária, proprietário,
contato, status da negociação, notas) persistida por projeto e **incluída nos exports**
CSV/Excel/KML.

> ⚠️ **Honestidade do método:** matrícula e proprietário **não têm API pública no Brasil**
> (dados de cartório, protegidos pela LGPD). O sistema entrega os links oficiais de consulta
> (ONR/Registradores — certidão paga —, SIGEF/INCRA para rural, geoportal da prefeitura para
> a inscrição do IPTU) e você registra o resultado na ficha. O score automatiza a **triagem
> técnica** de viabilidade; a due diligence legal (certidão, ônus, débitos) e o levantamento
> planialtimétrico para projeto executivo continuam etapas obrigatórias antes da compra.

> 📄 Documentação completa em [`docs/`](docs):
> [Requisitos](docs/REQUISITOS.md) · [Arquitetura](docs/ARQUITETURA.md) · [Pesquisa](docs/PESQUISA.md)

## Stack

- **Backend/API:** Python 3.14 + FastAPI (jobs em background com progresso)
- **Dados reais (sem chave):**
  - **Microsoft Building Footprints** — fonte DEFAULT de edificações (tiles por
    quadkey, parse via DuckDB, cache local em FlatGeobuf). Ex. real: ~1.800
    footprints num trecho de 2×2 km de Goiânia onde o OSM tem ~40.
  - **OSMnx** — Nominatim (geocodificação + limite municipal), Overpass (vias,
    exclusões, edificações OSM complementares)
  - **Overture Maps** opcional via **DuckDB** (lenta); **Google Open Buildings**
    opcional via GEE
- **Geoprocessamento:** GeoPandas · Shapely (STRtree p/ cidade inteira) · pyproj ·
  **pyogrio** (I/O vetorial — *sem fiona*)
- **Frontend:** Leaflet (canvas p/ milhares de polígonos) + **Esri World Imagery**
- **Export:** simplekml (KML) · openpyxl (Excel) · CSV

Tudo no caminho default roda **com dados reais e sem API key**. O Google Earth Engine é um
provider **opcional e plugável** (índices NDVI/NDBI sobre Sentinel-2).

## Deploy em Produção (Render)

O sistema está hospedado em: **https://ambgeo-lotepro.onrender.com**

| Campo | Valor |
|-------|-------|
| URL | https://ambgeo-lotepro.onrender.com |
| Usuário | `admin` |
| Senha | `u9epGTVQLv5cDzQfsUZfPLDKG8fXgyuANr3eKxsbUo0=` |
| Dashboard Render | https://dashboard.render.com/web/srv-d8opgatckfvc7380go7g |

> Plano free: dorme após 15 min de inatividade — primeiro acesso após o sono demora ~30s.
> Dados de projetos são **efêmeros** (ficam em `/tmp` e resetam no restart).
> Para persistência real: ativar disco no Render ($7/mês) ou migrar storage para Supabase.

### Redesployar / Novo deploy

O repo já tem `render.yaml` + `Dockerfile`. Para criar um novo serviço do zero via API:

```bash
# 1. Pegar o owner ID da conta Render
curl -H "Authorization: Bearer <RENDER_API_KEY>" https://api.render.com/v1/owners

# 2. Criar o serviço (Docker, plano free, branch develop)
curl -X POST https://api.render.com/v1/services \
  -H "Authorization: Bearer <RENDER_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "autoDeploy": "yes",
    "branch": "develop",
    "name": "ambgeo-lotepro",
    "ownerId": "<OWNER_ID>",
    "repo": "https://github.com/grupo-mngt-org/ambgeo-lotepro",
    "type": "web_service",
    "serviceDetails": {
      "dockerfilePath": "./Dockerfile",
      "env": "docker",
      "plan": "free",
      "region": "ohio"
    },
    "envVars": [
      {"key": "LOTEPRO_USER",     "value": "admin"},
      {"key": "LOTEPRO_PASSWORD", "generateValue": true},
      {"key": "LOTEPRO_SECRET",   "generateValue": true},
      {"key": "LOTEPRO_DATA_DIR", "value": "/tmp/lotepro-data"},
      {"key": "open_router_key",   "value": "<OPENROUTER_KEY>"},
      {"key": "open_router_model", "value": "nvidia/nemotron-3-ultra-550b-a55b:free"},
      {"key": "open_router_model2","value": "nex-agi/nex-n2-pro:free"},
      {"key": "open_router_model3","value": "poolside/laguna-m.1:free"}
    ]
  }'
```

> **Nota:** o repo GitHub precisa ser **público** para o Render acessar sem OAuth.
> As chaves ficam em `infra_envs` (interno Grupo MNGT).

---

## Como rodar

```bash
# 1. instalar dependências (uv usa Python 3.12 e o uv.lock; no Windows, NÃO use fiona)
uv sync

# 2. gerar dados de exemplo (Goiânia/GO)
uv run python scripts/make_sample.py

# 3. subir a API + frontend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. abrir no navegador
#    http://127.0.0.1:8000      (login dev: admin / lotepro)
```

> No Windows, `start.bat` faz os passos 1, 3 e 4 automaticamente (duplo-clique).

### Rodar com Docker (API + Postgres)

```bash
docker compose up --build       # API em http://localhost:8040, Postgres em 127.0.0.1:5436
```

### Fluxo no navegador (dados REAIS)
1. **Entrar** (admin / lotepro).
2. Escolha o modo: **🏙️ Cidade inteira** (default) ou **📍 Endereço + raio**.
3. **Digite a cidade** (autocomplete de municípios) e clique **Analisar cidade
   inteira** — acompanhe o progresso (limite municipal → malha viária →
   edificações → quadras → detecção → score). A 1ª análise de uma região baixa
   os footprints Microsoft (~50 MB/tile) e fica em **cache** para as próximas.
4. Veja o **relatório multi-cenário**, o **ranking dos melhores lotes** e clique
   num lote para abrir popup com score, ficha (matrícula/CRM) e o
   **🏘️ Estudo de implantação**.
5. No estudo, ajuste **testada/profundidade do lote, casa, recuos, via interna e
   orientação** — a implantação e as métricas (nº de casas, casas/ha,
   aproveitamento) recalculam em tempo real. **Salvar estudo** grava na ficha.
6. **Configurações avançadas**: fonte de edificações, filtros anti-falso-positivo
   (largura mínima do vazio, folga das edificações, teto de área), zoneamento
   e **exportação** CSV/Excel/KML.

> A análise usa defaults sensatos — você não precisa configurar nada para o caso comum.
> O gerador `scripts/make_sample.py` é apenas para testes offline.

## Motor de detecção (provider plugável)

| Provider | Roda sem chave? | O que faz |
|----------|-----------------|-----------|
| `footprint` (default) | ✅ | `gaps`: AOI − edificações → vazios. `parcels`: pontua lotes pela ocupação |
| `gee` (opcional) | ❌ (requer credenciais GEE) | NDVI/NDBI sobre Sentinel-2; stub plugável em [`app/providers/gee.py`](app/providers/gee.py) |

Regras de negócio editáveis (RF03): **área mínima** (default 500 m²) e **ocupação máxima**
(default 15%). Áreas recebem rótulo de **zoneamento** por *spatial join* e classificação de
**potencial** (alto/médio/baixo).

## API (resumo)

| Método | Rota |
|--------|------|
| POST | `/api/auth/login` |
| GET | `/api/geocode/suggest?q=&cities=1` &nbsp;— autocomplete (Photon); `cities=1` filtra municípios |
| POST | `/api/analyze/start` &nbsp;— análise em background (`mode: radius\|city`) → `{job_id}` |
| GET | `/api/jobs/{id}` &nbsp;— progresso/resultado do job |
| POST | `/api/analyze` &nbsp;— análise síncrona (scripts/compatibilidade) |
| POST | `/api/layout/preview` &nbsp;— **estudo de implantação** (estilo TestFit) em tempo real |
| GET | `/api/bolhas` &nbsp;— catálogo da prateleira (linhas, arquétipos, faixas MCMV) |
| POST | `/api/bolha/analyze` &nbsp;— **Motor de Bolhas (IA)**: inicia o estudo (job) → `{job_id}` |
| GET | `/api/projects/{id}/bolhas-map` &nbsp;— mapa de bolhas da cidade (determinístico) |
| PATCH | `/api/projects/{id}/lots/{lot}` &nbsp;— ficha do lote (matrícula, status, **layout salvo**) |
| GET / POST | `/api/projects` |
| POST | `/api/projects/{id}/source/osm` &nbsp;— busca dados reais (cidade + endereço + raio) |
| POST / GET | `/api/projects/{id}/layers/{aoi\|buildings\|zoning\|exclusions}` |
| POST | `/api/projects/{id}/detect` |
| GET | `/api/projects/{id}/results` |
| GET | `/api/projects/{id}/export.{csv\|xlsx\|kml}` |

Docs interativas (Swagger): `http://127.0.0.1:8000/docs`.

## Testes

```bash
python -m pytest -q              # testes do motor de detecção
python scripts/smoke_e2e.py      # smoke ponta a ponta (servidor precisa estar no ar)
```

## Habilitar Google Earth Engine (opcional)

```bash
pip install earthengine-api
# defina GEE_SERVICE_ACCOUNT + GEE_KEY_FILE, ou: earthengine authenticate
```
Sem credenciais, o provider `gee` retorna erro explicativo e o `footprint` segue funcionando.

## Configuração (variáveis de ambiente)

Veja [`.env.example`](.env.example). Principais: `LOTEPRO_USER`, `LOTEPRO_PASSWORD`,
`LOTEPRO_SECRET`, `LOTEPRO_DATA_DIR`. Para o **Motor de Bolhas (IA)**:
`open_router_key` + `open_router_model`/`open_router_model2`/`open_router_model3`
(o `.env` é carregado automaticamente; sem chave, o estudo roda em modo determinístico).

## Roadmap (fora do MVP)

PostGIS/multiusuário (no Render: usar **Supabase client**, porta 5432 bloqueada) ·
jobs assíncronos · ETL de zoneamento legado (CAD) · visão computacional (YOLO/Mask R-CNN).
