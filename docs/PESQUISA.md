# Lote Pro — Pesquisa Técnica

Notas de pesquisa que embasaram as decisões de arquitetura.

## 1. Como a AmbGEO (e o mercado) detecta vazios urbanos

Três técnicas centrais, citadas no `espec.md`:

1. **Índices espectrais** sobre imagem de satélite:
   - **NDVI** = (NIR − RED) / (NIR + RED) → vegetação (alto = verde).
   - **NDBI** = (SWIR − NIR) / (SWIR + NIR) → área construída (alto = concreto/telhado).
   - Solo exposto/terreno baldio: NDVI baixo a médio + NDBI baixo (sem assinatura de telhado).
2. **Morfologia matemática / taxa de ocupação**: razão entre área construída e área total do
   polígono; permite ignorar construções pequenas (edículas) abaixo de um limiar.
3. **Building Footprints**: subtrair a área construída (footprints) da área total do lote.

> Decisão: o MVP implementa **(2) + (3)** de forma local e determinística (sem credenciais),
> e deixa **(1)** como provider `gee` opcional. Isso entrega valor imediato e mantém fidelidade
> ao know-how para evolução.

## 2. Fontes de dados gratuitas / abertas

| Necessidade | Fonte gratuita escolhida | Observação |
|-------------|--------------------------|------------|
| Basemap satélite | **Esri World Imagery** (tiles `services.arcgisonline.com`) | Sem chave; uso permitido com atribuição |
| Alternativa basemap | **Sentinel-2 cloudless** (EOX) / OpenStreetMap | Sem chave |
| Footprints de edificações | **Microsoft Building Footprints** e **Google Open Buildings** | Dados abertos (ODbL/CC BY); cobertura Brasil parcial |
| Imagem multiespectral | **Sentinel-2 (Copernicus)** via Google Earth Engine | Tier de pesquisa gratuito; exige credencial |
| Limites/zoneamento | Portais das prefeituras / IBGE / **osint-brazuca** (índice de fontes BR) | Frequentemente em formatos legados → ETL |
| Cadastro rural | **SIGEF/INCRA** (ref. GeoINCRA) | Modelo de dados Vertex/Limit/Parcel |

Evitados por serem pagos/freemium: Google Maps Static/Street View **tiles**, Mapbox (limite freemium).
StreetView é usado apenas como **URL de navegação** (`https://www.google.com/maps?q=&layer=c&cbll=lat,lon`).

## 3. Projetos de referência avaliados

### GeoINCRA (`OpenGeoOne/GeoINCRA`)
- Plugin **QGIS em Python** para georreferenciamento rural no padrão INCRA/SIGEF.
- **Reaproveitável (conceitual):** o esquema *GeoRural* (Vertex / Limit / Parcel) e a conversão
  CSV → geometria. Inspirou o modelo `Parcel` (polígono + metadados) do Lote Pro.
- Não reaproveitável diretamente: é acoplado à API do QGIS; foco rural, não urbano.

### osint-brazuca (`osintbrazuca/osint-brazuca`)
- **Índice curado** de fontes/portais brasileiros de OSINT (não é biblioteca de código).
- **Uso:** catálogo de portais públicos para obter zoneamento, cadastro e endereços por município.

### OSMnx (`gboeing/osmnx`) — **adotado para dados reais** (~5k★)
- Biblioteca Python madura e muito popular que encapsula **Nominatim** (geocodificação) e
  **Overpass** (consulta OSM). Gratuita, sem chave, instala no Python 3.14.
- **Uso no Lote Pro** (`app/core/osm.py`):
  - `ox.geocode(cidade + endereço)` → ponto central da análise;
  - `ox.features_from_point(tags={"building": True})` → **edificações reais**;
  - `ox.features_from_point(tags={"highway": True})` → **malha viária real**, cujo buffer é
    subtraído da AOI para particioná-la em **quadras** (lotes candidatos).
- **Limitação honesta:** a cobertura/granularidade depende do OSM. Em parte do Brasil há
  edificações faltando e lotes apenas em nível de quadra → quadras sem prédios mapeados
  aparecem como "vazias". Mitigação: fonte Overture (abaixo), provider `gee` ou footprints próprios.

### Overture Maps Buildings — **adotado como fonte opcional de alta cobertura**
- Dataset aberto que **funde OSM + Google + Microsoft + Esri** (footprints). Consultado por
  **bounding box** direto do parquet público via **DuckDB** (extensões `spatial` + `httpfs`),
  sem chave, região `us-west-2`, release `2026-05-20.0`.
- **Medição comparativa (Praça Cívica, Goiânia, bbox ~500 m):** Overture = **2.147** edificações
  vs OSM ≈ **38** no mesmo trecho. Ganho de cobertura enorme → reduz falsos-positivos.
- **Trade-off:** a varredura remota é **lenta (~3–4 min no 1º acesso)**, pois o filtro por bbox
  ainda inspeciona muitos arquivos parquet globais. Por isso é **opcional**; o OSM segue como
  default rápido. Os footprints baixados são **persistidos** na camada do projeto (re-detecção
  instantânea). Implementação em `app/core/overture.py`.

## 4. Cálculo de área correto (CRS)

- Dados de entrada normalmente em **EPSG:4326** (graus) — calcular área aí dá valores errados.
- Solução: reprojetar para CRS métrico local antes de medir. Usamos
  `GeoDataFrame.estimate_utm_crs()` (pyproj) para achar o **UTM** apropriado e medir em m².

## 5. Decisões-chave (resumo)

1. **pyogrio, não fiona** — fiona não tem wheel para Python 3.14/Windows.
2. **Footprint-subtraction como default executável**; GEE plugável e opcional.
3. **Esri World Imagery** como basemap; nada que exija chave paga.
4. **Persistência em arquivo** (GeoPackage/GeoJSON) no MVP; PostGIS no roadmap.
5. **Auth simples** com token assinado (stdlib) — sem dependências pesadas.
