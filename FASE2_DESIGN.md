# Fase 2 — Design (Postgres + Alembic + multi-user)

> Decidido em 2026-06-26. Escopo **Opção A** (ver `PLANO_MIGRACAO_AMBGEO_LOTEPRO.md` e `ANALISE_SISTEMA.md`).

## Decisões (do usuário)

1. **Opção A**: `projects` + `lots` (resultados) + CRM + `users` no Postgres. Geometrias de **input** (`aoi/buildings/zoning`) continuam em `.gpkg` (arquivo).
2. **Sem multi-tenant**: todos os usuários autenticados veem **todos** os projetos e análises. Guardamos só `created_by` para auditoria — **nenhum filtro de acesso por usuário**.
3. **Google OAuth** como login (padrão mngpt).
4. **Não perder análises feitas**: backfill **não-destrutivo** importa `data/projects/*` para o banco; os `.gpkg`/JSON **não são apagados** (ficam como backup).
5. **Não re-rodar análises que gastam token**: `results` e o estudo de IA do Motor de Bolhas (`bolha`) são persistidos no banco — uma vez calculados, nunca recalculados.

## Schema (SQLAlchemy / Alembic `0001_initial`)

### `users`
| coluna | tipo | nota |
|---|---|---|
| id | UUID PK | |
| email | text unique not null | |
| name | text | |
| picture | text null | avatar Google |
| google_sub | text unique | subject id do Google |
| role | text default 'user' | |
| created_at | timestamptz | |

### `projects` (de `meta.json`)
| coluna | tipo | nota |
|---|---|---|
| id | text PK | **mantém o hex de 12 chars atual** (preserva URLs/frontend e dados existentes) |
| name | text | |
| created_at | timestamptz | |
| created_by | UUID FK users.id null | **auditoria apenas** (sem filtro) |
| last_detect | jsonb null | `{count, mode, profile, source}` |

### `lots` (de `results.gpkg` — os lotes detectados)
| coluna | tipo | nota |
|---|---|---|
| id | bigserial PK | **ID ESTÁVEL** (resolve a lacuna do índice frágil) |
| project_id | text FK projects.id, index | |
| seq | int | índice original no projeto (o antigo lot_id; ordenação/referência) |
| area_m2, occupation, lat, lon | float | |
| potential, color, zoning, street_view | text | |
| score, slope_pct, elev_range_m, frontage_m, compactness | float null | enriquecimento |
| grade, flags | text null | |
| score_breakdown | jsonb null | |
| geom_wkb | bytea | **polígono do lote em WKB** (geopandas via `shapely.wkb`; sem PostGIS) |
| created_at | timestamptz | |

### `lot_crm` (de `lots.json` — CRM + estudo de IA)
| coluna | tipo | nota |
|---|---|---|
| lot_id | bigint FK lots.id PK | 1:1 com o lote |
| matricula, inscricao, proprietario, contato, status, notas | text null | |
| layout | jsonb null | estudo de implantação salvo |
| bolha | jsonb null | **estudo do Motor de Bolhas (IA) — token-saver** |
| updated_at | timestamptz | |
| updated_by | UUID FK users.id null | auditoria |

> **Jobs**: a fila (`jobs.py`) fica **em memória por enquanto** (é só rastreamento de progresso; o resultado da análise já é persistido em `lots`). Vira tabela só se precisarmos sobreviver a restart no meio de uma análise — fora do escopo agora.

## ⚠️ Ponto técnico: re-detecção e o vínculo do CRM

IDs estáveis resolvem o índice frágil **dentro de uma detecção**. Mas **re-detectar um projeto gera um conjunto novo de lotes** — os ids antigos deixam de existir. Comportamento da Fase 2:

- Re-detecção é uma ação **explícita e rara**; o fluxo normal **não re-detecta** (os `results` ficam no banco, então o mapa/ranking estão sempre lá sem recálculo).
- Ao re-detectar, os lotes do projeto são **substituídos** (e o CRM/bolha vinculado a eles vai junto).
- **Re-vincular CRM por correspondência espacial** (casar lote novo ao antigo por centroide/sobreposição) fica como **melhoria futura** — não é necessário para o objetivo atual de não perder o que já foi feito.

## ~~Backfill~~ — DESCARTADO (2026-06-26)

Não há nada em produção, então **não haverá script de backfill**. Os `data/projects/*` locais são apenas dados de teste e não precisam ser preservados. Fase 2a começa com o banco vazio.

## (Referência) Estratégia de backfill — não será usada

Script `scripts/migrate_fs_to_db.py`, rodado **uma vez** após `alembic upgrade head`:

1. Para cada `data/projects/<id>/`:
   - `meta.json` → **upsert** em `projects`.
   - `results.gpkg` → insere linhas em `lots` (geom → WKB). **Pula se o projeto já tem lotes** (idempotente).
   - `lots.json` → insere em `lot_crm`, casando pela `seq` (índice) com `lots.seq`.
2. **Nunca apaga** os arquivos `.gpkg`/JSON — permanecem como backup.
3. Re-executável sem duplicar.

Rodar no servidor contra o volume `lotepro_data` para importar as análises de produção.

## Mudanças de código

- `app/database.py` (engine + `Base` + `get_db()`), `app/models.py`, `alembic.ini` + `alembic/env.py` + `0001_initial` — mecânico, padrão mngpt.
- `app/core/store.py`: `projects`/`lots`/CRM passam a ler/gravar no banco. `save_layer/load_layer` de **input** (`aoi/buildings/zoning`) continuam em arquivo. `save_layer("results")` → grava em `lots`; `load_layer("results")` → reconstrói o GeoDataFrame a partir de `lots`.
- `compose.yml`: `command: sh -c "uv run alembic upgrade head && uv run uvicorn ..."`.
- **Auth Google OAuth**: tabela `users` + fluxo OAuth + botão no frontend (`index.html`/`app.js`).

## Incrementos sugeridos (risco baixo, CLAUDE.md: "validar incrementos pequenos")

- **Fase 2a — Persistência (núcleo do objetivo): ✅ FEITA E VALIDADA (2026-06-26).** Alembic + models (`users`, `projects`, `lots`, `lot_crm`) + migração do `store.py` (projects/lots/crm no banco; inputs aoi/buildings/zoning em arquivo). Sem backfill (nada em prod). Auth continua single-user (HMAC) temporariamente. Validado: migration cria 5 tabelas, IDs de lote estáveis (gdf reescrito in-place), CRM com layout/bolha em JSONB, `/results` GeoJSON íntegro, e **dados sobrevivem a restart** (projects/lots/lot_crm persistidos). **Entrega: dados no banco, nada se perde, nada recalcula.**
- **Fase 2b — Auth:** `users` + Google OAuth + frontend. **Entrega: login Google multi-usuário (visão compartilhada).**
