# Análise do Sistema — ambgeo-lotepro (Lote Pro)

> Insumo para decidir o escopo de persistência da **Fase 2** (ver `PLANO_MIGRACAO_AMBGEO_LOTEPRO.md`).
> Levantado em 2026-06-25 a partir do código em `app/`.

## 1. O que o sistema faz (em uma frase)

Detecta e qualifica **lotes urbanos vazios ou subutilizados** (subtração quadra − edificações), pontua a viabilidade técnica de cada lote (0–100) com base em relevo/acesso/testada/forma/entorno, e recomenda qual **arquétipo de produto imobiliário ("Bolha", alinhado ao MCMV)** construir — via IA (OpenRouter) com fallback determinístico.

## 2. Processo de análise (pipeline)

Dois modos convergem no mesmo enrich+score:

| Etapa | Radius (endereço + raio) | Citywide (cidade inteira) | Módulo |
|---|---|---|---|
| 1. Definir área | ponto + raio (AOI = 1 bloco) | limite municipal (Nominatim) | `analysis.py` / `citywide.py` |
| 2. Vias | OSM no entorno | malha viária inteira (OSMnx) | `osm.py` |
| 3. Edificações | OSM ou Microsoft | Microsoft (fallback OSM/Overture/GEE) | `msbuildings.py`, `osm.py`, `overture.py`, `gob.py` |
| 4. Exclusões | — | praças/escolas/água | `osm.py` |
| 5. Quadras | AOI genérico | município − (vias + exclusões) → blocos | `citywide.py` |
| 6. Detectar vazios | quadra − footprints (buffer 1.5m), filtra largura/testada/área/ocupação | idem por quadra | `detect.py`, `pipeline.py` |
| 7. Enriquecer + score | relevo(DEM)+acesso+testada+forma+infra → score 0–100, grade A–D | igual, **DEM só top-150** (cota API) | `enrich.py`, `score.py`, `dem.py` |
| 8. Relatório | 3 cenários (conservador/moderado/amplo) | idem | `report.py` |
| 9. Motor de Bolhas | recomenda produto por lote (IA ou heurístico) | idem | `bolhas.py`, `ai.py` |

**Score (score.py):** 6 critérios ponderados — slope (25), infra (20), area_fit (20), access (15), frontage (10), shape (10); critérios sem dado são renormalizados (não punem). Grade A≥80, B≥65, C≥50, D<50.

**Motor de Bolhas (bolhas.py):** ranking determinístico `score_fit()` roda sempre; se OpenRouter configurado, IA monta estudo completo (bolha, faixa MCMV, VGV/custo-alvo, módulos, riscos, checklist); sem chave ou em erro/timeout → cai no heurístico.

## 3. APIs / fontes externas

| Fonte | Para quê | Auth | Cache em disco |
|---|---|---|---|
| **OSM** (Photon, Nominatim, Overpass via OSMnx) | autocomplete, geocode, geocode reverso, footprints, vias, exclusões | aberta | `~/.cache/osmnx/` (global do SO) + in-memory |
| **Microsoft Building Footprints** | footprints ML (cobertura ~7× OSM no BR) | aberta | **`data/cache/msbuildings/{quadkey}.fgb` (GLOBAL, 100s MB)** + índice CSV |
| **Overture Maps** (via DuckDB/S3) | footprints fundidos (fallback) | aberta | não (query remota) |
| **OpenTopoData / SRTM 30m** | elevação/DEM → declividade | aberta | **`cache/dem_cache.json` (GLOBAL, pequeno)** |
| **Google Earth Engine** | Google Open Buildings, Dynamic World, Sentinel-2 | `GEE_SERVICE_ACCOUNT`+`GEE_KEY_FILE` (opcional) | não |
| **OpenRouter** | IA do Motor de Bolhas | `OPENROUTER_KEY` (opcional → heurístico) | não |
| **BrasilAPI /cnpj** | dados cadastrais CNPJ do proprietário | aberta | in-memory `lru_cache` |
| **DataJud / CNJ** | processos judiciais por nº | chave pública (`DATAJUD_API_KEY`) | in-memory |
| **SICAR / CAR** | imóvel rural cadastrado | aberta (cookie) | in-memory |
| **Google Street View** | link da foto do lote | — | — (URL passiva) |

Limites relevantes: Nominatim 1 req/s; OpenTopoData ~1000 req/dia (por isso DEM só top-150 no citywide).

## 4. O que é persistido HOJE (filesystem)

Tudo em `data/projects/<id>/` (id = `uuid4().hex[:12]`):

| Arquivo | Formato | Escreve | Lê | Conteúdo |
|---|---|---|---|---|
| `meta.json` | JSON | create/update_meta | list/get | `{id, name, created_at, last_detect:{count,mode,profile,source}}` |
| `aoi.gpkg` | GeoPackage (EPSG:4326) | save_layer (upload/OSM) | detect | polígono(s) da área. **Input** |
| `buildings.gpkg` | GeoPackage | save_layer | detect | footprints. **Input** |
| `zoning.gpkg` | GeoPackage | upload | detect | zonas (opcional). **Input** |
| `exclusions.gpkg` | GeoPackage | (radius) | — | áreas subtraídas. Quase-input |
| `results.gpkg` | GeoPackage | detect/analyze | export/results/bolhas-map | **RESULTADO**: lote + area_m2, occupation, potential, score, grade, slope_pct, frontage_m, compactness, flags, score_breakdown(JSON), zoning, lat/lon, street_view |
| `lots.json` | JSON | set_lot_info (PATCH /lots, bolha) | get_lots_info (UI/export) | **CRM**: por lot_id → `{matricula, inscricao, proprietario, contato, status, notas, layout{}, bolha{}, updated_at}` |

**Status enum do CRM:** `novo | analisando | contato_feito | negociando | descartado | comprado`.

**Jobs (`jobs.py`):** fila **em memória** (thread + lock), só últimos 50, `{id,status,stage,progress,result,error}`. **Tudo se perde no restart.**

### Lacunas estruturais (importantes para Fase 2)
- **Sem owner/multi-tenant:** auth é só checkpoint; `user` autenticado nunca é gravado. Qualquer usuário vê todos os projetos.
- **lot_id é frágil:** índice inteiro do `results.gpkg`; re-analisar um projeto pode reembaralhar os ids → o vínculo com o CRM (`lots.json`) quebra.
- **Caches globais grandes fora do projeto:** `msbuildings/` (100s MB) e `dem_cache.json`.

## 5. Implicações para a Fase 2 (o que vai pro Postgres)

Classificando por natureza do dado:

**A) Estado de negócio — claramente relacional (deve ir pro Postgres):**
- `projects` (de `meta.json`) — + coluna **owner** (resolve multi-user)
- CRM `lots` (de `lots.json`) — matrícula/proprietário/contato/status/notas + `layout` e `bolha` como JSONB
- `jobs` (opcional) — se quiser sobreviver a restart

**B) Geometrias (`*.gpkg`) — é a decisão Opção A vs B:**
- **Inputs** (`aoi`, `buildings`, `zoning`, `exclusions`): grandes, escritos uma vez, lidos pelo detect. Bons candidatos a **continuar em arquivo/blob** (caminho no DB).
- **`results`**: é o resultado consultado (export, mapa, ranking). Atributos são tabulares (score, grade, flags…) + 1 geometria. **Esse é o que mais ganha indo pra tabela** (`lots` com colunas + geom).

**C) Caches externos (`msbuildings/`, `dem_cache.json`):** globais e reutilizáveis. Migráveis a tabelas spatial/lookup, mas são **otimização**, não bloqueador — podem ficar em disco/volume.

### Leitura recomendada da decisão A vs B
- **Opção A (metadados+CRM no Postgres, geometrias em arquivo):** resolve o que mais dói hoje — perda de dados no restart do Render, multi-user, e o vínculo lote↔CRM (ids estáveis no DB). Mexe pouco no geoprocessamento. **Menor risco, maior retorno imediato.**
- **Opção B (tudo em PostGIS):** mais "correto" e portável, habilita consultas espaciais no banco, mas reescreve `store.py`/`io.py`, exige `geoalchemy2`+imagem PostGIS e cria extensão no `env.py`. **Maior esforço; justifica-se se as queries espaciais no banco virarem requisito.**

**Sugestão:** começar pela **Opção A** com o `results` indo para uma tabela `lots` (atributos + geom como WKB/GeoJSON ou PostGIS leve), CRM e projects relacionais com **owner**, e ids de lote **estáveis** (PK no banco, não o índice do gpkg). Inputs (`aoi/buildings/zoning`) e caches globais ficam em arquivo/volume nesta etapa. PostGIS pleno (Opção B) fica como evolução quando houver query espacial no banco.
