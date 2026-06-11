Este é um documento de **Especificação de Requisitos** detalhado, consolidando as necessidades expressas na sua conversa com a AmbGEO e agregando a inteligência técnica necessária para que sua equipe de TI possa estimar o esforço de desenvolvimento "do zero".

---

# Documento de Especificação Técnica: Projeto "Lote Pro" (Prospecção Inteligente de Áreas)

## 1. Objetivo do Projeto
Desenvolver uma plataforma de inteligência geográfica para identificar e qualificar terrenos baldios ou subutilizados em perímetros urbanos, utilizando processamento de imagens de satélite e cruzamento de dados vetoriais (zoneamento e expansão urbana) para acelerar a prospecção imobiliária.

---

## 2. Pesquisa de Referência (O "Know-How" da AmbGEO)
A AmbGEO utiliza predominantemente o **Google Earth Engine (GEE)** e linguagens como **Python**. O diferencial deles que deve ser replicado internamente baseia-se em:
1.  **Índices Espectrais:** Uso de algoritmos para identificar o que é solo exposto (NDBI - *Normalized Difference Built-up Index*) versus o que é vegetação (NDVI) versus o que é área construída.
2.  **Morfologia Matemática:** Algoritmos que calculam a "taxa de ocupação" de um polígono para decidir se uma construção pequena pode ser ignorada.
3.  **Integração de APIs:** Consumo de dados de *Building Footprints* (como os do Google ou Microsoft) para subtrair a área construída da área total do terreno.

---

## 3. Requisitos Funcionais (RF)

### RF01 - Gestão de Áreas de Interesse (AOI)
*   O sistema deve permitir o upload de arquivos vetoriais (Shapefile, KML ou GeoJSON) contendo as áreas de expansão urbana e o zoneamento da cidade.
*   O sistema deve permitir a seleção de uma cidade inteira como filtro primário.

### RF02 - Processamento de Imagens e Identificação
*   O sistema deve processar imagens de satélite (Sentinel-2, Landsat 8 ou Google High-Res) para classificar o uso do solo.
*   **Algoritmo de Detecção de Vazio:** Identificar polígonos que não possuam assinaturas espectrais de telhados/concreto em mais de X% de sua área.

### RF03 - Filtros de Qualificação (Regras de Negócio)
*   **Filtro de Área Mínima:** Excluir automaticamente qualquer área identificada que possua menos de 500 m² (parâmetro editável).
*   **Filtro de Ocupação:** Permitir construções pequenas (ex: edículas ou galpões pequenos) desde que a área construída seja inferior a 15% (parâmetro editável) da área total do lote.
*   **Cruzamento de Zoneamento:** Rotular as áreas encontradas de acordo com os dados de zoneamento importados (ex: "ZRE - Zona Residencial Especial").

### RF04 - Visualização e Interface Map-Centric
*   Exibir os resultados em um mapa interativo (Base Map: Google Satellite).
*   Colorir os polígonos identificados de acordo com o potencial de aproveitamento.
*   Permitir clicar em um polígono para ver: Coordenadas, Área total m², Zoneamento e Link direto para Google Street View.

### RF05 - Exportação de Leads
*   Gerar relatório em Excel/CSV com a lista de áreas encontradas, incluindo latitude/longitude e área calculada.
*   Exportar polígonos em KML para uso em campo.

---

## 4. Requisitos Não Funcionais (RNF)

### RNF01 - Performance e Escalabilidade
*   O processamento de uma cidade de médio porte (ex: 500 mil habitantes) não deve exceder 2 horas.
*   Uso de processamento em nuvem distribuído (Google Earth Engine API ou AWS/Azure com bibliotecas GDAL/Rasterio).

### RNF02 - Acurácia
*   O índice de falso-positivo (identificar um prédio como terreno vazio) deve ser inferior a 10%. *Nota: Isso exige calibração de filtros de sombra e reflectância.*

### RNF03 - Segurança e Acesso
*   O sistema deve ser acessível via navegador com autenticação por login/senha.
*   Separação de dados por projeto ou cidade.

### RNF04 - Disponibilidade de Dados
*   O sistema deve consumir dados de satélite atualizados (últimos 6 meses) para evitar a prospecção de terrenos que já foram construídos recentemente.

---

## 5. Stack Tecnológica Recomendada (Para o seu TI)

Para competir com a consultoria externa e garantir agilidade:

1.  **Linguagem:** Python 3.x (Líder em geoprocessamento).
2.  **Back-end Geo:** 
    *   **Google Earth Engine Python API** (Para processamento pesado de imagens sem custo de servidor local).
    *   **Geopandas / Shapely** (Para manipulação de polígonos e cálculos de área).
3.  **Banco de Dados:** **PostgreSQL com extensão PostGIS** (Essencial para armazenar e consultar coordenadas geográficas com performance).
4.  **Front-end:** **React.js** com biblioteca **Mapbox GL JS** ou **Leaflet** para visualização dos mapas.
5.  **Infraestrutura:** Dockerizado e hospedado em AWS ou Google Cloud.

---

## 6. Diferenciais para Orçamento (Onde mora o custo)

Para que seu time de TI orce corretamente, eles precisam considerar:
1.  **Custo de APIs:** O Google Maps API cobra por "Static Maps" e "Street View". O Google Earth Engine tem uma camada gratuita para pesquisa, mas para uso comercial estruturado possui custos de licença/nuvem.
2.  **Limpeza de Dados:** Dados de zoneamento de prefeituras costumam vir "sujos" ou em formatos legados (CAD). O time precisará de um tempo para o ETL (Extração e Limpeza) desses dados.
3.  **Visão Computacional (Opcional/Avançado):** Se os índices espectrais não forem suficientes, pode ser necessário treinar um modelo simples de IA (YOLO ou Mask R-CNN) para detectar especificamente "muros" ou "lajes".

---

Estude PESQUISE e utilize projetos prontos como 
https://github.com/osintbrazuca/osint-brazuca
https://github.com/OpenGeoOne/GeoINCRA
