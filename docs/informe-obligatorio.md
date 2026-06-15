# Informe del obligatorio: Machine Learning en Produccion

## 1. Resumen

El proyecto implementa una solucion de Machine Learning en Produccion para predecir el rating de peliculas de IMDb. La solucion cubre el ciclo completo desde la recoleccion de datos hasta el despliegue de una aplicacion web en AWS.

El flujo principal es:

1. Recolectar datos de peliculas y reviews desde IMDb.
2. Persistir datos crudos en S3 en formato Parquet.
3. Ejecutar un proceso ETL para construir un dataset de entrenamiento.
4. Entrenar y registrar un modelo de prediccion.
5. Exponer la solucion mediante una API FastAPI containerizada.
6. Desplegar la aplicacion en AWS ECS Fargate usando Terraform.

La solucion busca aplicar conceptos de MLOps vistos en clase: automatizacion de pipelines, versionado de datos, separacion entre datos crudos y procesados, tracking de modelos, model registry, despliegue reproducible, gestion de secretos y monitoreo basico.

## 2. Objetivo del proyecto

El objetivo es construir una aplicacion capaz de estimar el rating esperado de una pelicula a partir de atributos disponibles en IMDb, como año, duración, metascore, generos, director, cast principal y analisis de las reviews de usuarios.

Ademas del modelo predictivo, el foco del obligatorio esta en construir una arquitectura productiva alrededor del modelo. Por eso el proyecto no se limita al entrenamiento, sino que incluye ingesta de datos, procesamiento, almacenamiento, despliegue cloud e infraestructura como codigo.

## 3. Arquitectura general

La arquitectura propuesta se compone de los siguientes bloques:

| Componente | Tecnologia | Responsabilidad |
| --- | --- | --- |
| Scraper | Python, Playwright | Extraer peliculas y reviews desde IMDb |
| Data lake | AWS S3 | Almacenar datos crudos, procesados y de inferencia |
| ETL | Python, pandas, pyarrow | Transformar datos crudos en dataset de entrenamiento |
| Tracking y registry | Weights & Biases | Registrar experimentos, metricas y modelos |
| API | FastAPI | Exponer endpoints para estado, peliculas, modelo y prediccion |
| Container | Docker | Empaquetar la aplicacion para ejecucion reproducible |
| Infraestructura | Terraform | Crear recursos cloud de forma declarativa |
| Despliegue | AWS ECS Fargate, ECR, ALB | Ejecutar la API en produccion |
| Logs | AWS CloudWatch | Observar comportamiento de la aplicacion |

El flujo de alto nivel es:

```text
IMDb
  -> Scraper
  -> S3 raw: movies/ y reviews/
  -> ETL
  -> S3 processed: training_dataset.parquet
  -> Entrenamiento
  -> W&B artifact: modelo versionado
  -> FastAPI
  -> Docker / ECR
  -> ECS Fargate + ALB
```

## 4. Ingesta de datos

La ingesta se realiza con un scraper de IMDb implementado en Python. El scraper obtiene informacion de peliculas y reviews, y guarda los resultados en formato local y en S3.

Datos recolectados para peliculas:

- Identificador IMDb.
- Titulo.
- Año.
- Rating IMDb.
- Cantidad de votos.
- Generos.
- Director/es.
- Reparto principal.
- Duracion.
- Certificado de edad.
- Metascore.
- Sinopsis.

Datos recolectados para reviews:

- Pelicula asociada.
- Usuario.
- Rating de la review.
- Texto de la review.
- Votos de utilidad.

El scraper contempla que IMDb puede requerir login para acceder a reviews completas. Para eso existe un flujo manual que guarda una sesion local y permite reutilizarla en corridas posteriores.

## 5. Almacenamiento y versionado de datos

Los datos se almacenan en S3 en formato Parquet. Cada corrida del scraper genera archivos con timestamp, evitando sobrescribir datos anteriores.

Estructura esperada:

```text
s3://mlp-imdb-data/
  imdb/
    movies/
      scraped_date=YYYY-MM-DD/
        run_YYYYMMDD_HHMMSS.parquet
    reviews/
      scraped_date=YYYY-MM-DD/
        run_YYYYMMDD_HHMMSS.parquet
    processed/
      training_dataset.parquet
    inference/
      inference_dataset.json
```

Esta organizacion permite aplicar un concepto importante de MLOps: trazabilidad de datos. Si un modelo fue entrenado con determinada version del dataset, se puede identificar de que corridas del scraper provienen los datos.

## 6. ETL y feature engineering

El proceso ETL transforma los datos crudos en un dataset plano listo para entrenar.

Pasos principales:

1. Leer peliculas y reviews desde S3.
2. Deduplicar peliculas repetidas, conservando la version mas reciente.
3. Agregar estadisticas de reviews por pelicula.
4. Codificar generos como columnas binarias multi-hot.
5. Codificar certificado de edad con one-hot encoding.
6. Eliminar filas sin target.
7. Guardar el dataset procesado como Parquet.
8. Generar un JSON de inferencia para la aplicacion.

Features generadas:

| Feature | Descripcion |
| --- | --- |
| `year` | Anio de estreno |
| `runtime_min` | Duracion de la pelicula |
| `metascore` | Puntaje de criticos |
| `genre_*` | Generos codificados como columnas binarias |
| `cert_*` | Certificado de edad codificado como columnas binarias |
| `num_reviews` | Cantidad de reviews recolectadas |
| `avg_review_rating` | Promedio de rating de las reviews |
| `avg_helpful_votes` | Promedio de votos utiles |
| `imdb_rating` | Variable objetivo |

Algunas columnas se excluyen o se dejan para trabajo futuro:

| Columna | Motivo |
| --- | --- |
| `votes` | Puede introducir leakage porque esta muy relacionada con el rating final |
| `title` | Texto libre que requiere otro procesamiento |
| `plot` | Puede usarse con embeddings en una etapa posterior |
| `directors` | Variable categorica de alta cardinalidad |
| `main_cast` | Lista compleja de actores, requiere codificacion especifica |

## 7. Entrenamiento del modelo

El entrenamiento debe tomar como entrada el archivo:

```text
s3://mlp-imdb-data/imdb/processed/training_dataset.parquet
```

El dataset se separa en variables predictoras y target:

```python
X = df.drop(columns=["imdb_id", "imdb_rating"])
y = df["imdb_rating"]
```

Como primera aproximacion se puede usar un modelo de regresion simple, por ejemplo:

- Linear Regression como baseline.
- Random Forest Regressor.
- Gradient Boosting Regressor.
- XGBoost o LightGBM si se desea comparar modelos mas potentes.

Metricas recomendadas:

- MAE: error absoluto promedio, facil de interpretar en escala de rating 1 a 10.
- RMSE: penaliza errores grandes.
- R2: explica la variabilidad capturada por el modelo.

### 7.1. Prevencion de data leakage y training-serving skew

En un sistema de Machine Learning en Produccion no alcanza con que el modelo tenga buenas metricas offline. Tambien es necesario asegurar que el modelo no aprenda informacion que no estaria disponible al momento de predecir y que el procesamiento usado en entrenamiento sea el mismo que se usa en inferencia.

#### Data leakage

Data leakage ocurre cuando el modelo usa, directa o indirectamente, informacion del futuro o informacion demasiado cercana al target. Esto genera metricas artificialmente buenas durante entrenamiento, pero mal desempenio en produccion.

Medidas aplicadas o recomendadas para este proyecto:

| Riesgo | Prevencion |
| --- | --- |
| Usar `imdb_rating` como feature | Separar explicitamente `X` e `y`, dejando `imdb_rating` solo como target |
| Usar `votes` como predictor | Excluir `votes`, porque esta directamente relacionado con la popularidad y consolidacion del rating |
| Usar reviews posteriores al momento de prediccion | Definir si la prediccion representa una pelicula nueva o una pelicula ya publicada; si es nueva, no usar reviews reales posteriores |
| Mezclar duplicados entre train y test | Deduplicar por `imdb_id` antes del split |
| Hacer transformaciones mirando todo el dataset | Ajustar imputadores, escaladores y encoders solo con train, y luego aplicarlos a validacion/test |
| Elegir modelo mirando el test final | Usar train/validation para seleccion de modelo y reservar test para evaluacion final |

Para el caso de reviews, una decision importante es distinguir entre dos escenarios:

- Prediccion pre-estreno o temprana: no deberian usarse reviews de usuarios, porque todavia no existen.
- Prediccion post-estreno: se pueden usar reviews, pero debe registrarse la fecha de corte para evitar usar informacion posterior al momento que se quiere simular.

#### Training-serving skew

Training-serving skew ocurre cuando los datos que recibe el modelo en produccion no pasan por el mismo procesamiento que los datos usados para entrenar. Esto puede pasar si el ETL de entrenamiento y la API implementan transformaciones por separado.

Medidas recomendadas:

| Riesgo | Prevencion |
| --- | --- |
| Columnas distintas entre entrenamiento e inferencia | Guardar junto al modelo la lista exacta de features esperadas |
| One-hot encoding inconsistente | Persistir el encoder o definir un esquema fijo de columnas |
| Diferente tratamiento de nulos | Usar el mismo imputador entrenado en train |
| Cambios manuales en la API | Reutilizar una funcion o pipeline compartido de preprocesamiento |
| Tipos de datos diferentes | Validar input con un schema antes de predecir |
| Modelo actualizado sin actualizar preprocessing | Versionar modelo y preprocesamiento como un unico artifact |

Una buena practica para este proyecto es registrar en W&B un artifact que contenga:

- Modelo entrenado.
- Pipeline de preprocesamiento.
- Lista de columnas/features.
- Version del dataset usado.
- Metricas de validacion.

De esa forma, la API puede cargar un unico artifact productivo y aplicar exactamente las mismas transformaciones que se usaron durante entrenamiento.

En este proyecto, la estrategia propuesta para reducir training-serving skew es que la aplicacion en produccion no reconstruya las features manualmente. En su lugar, la UI muestra una lista de peliculas disponibles y, cuando el usuario selecciona una, la API obtiene todos los datos ya procesados desde `inference_dataset.json`.

Ese JSON de inferencia es generado por el mismo ETL que produce `training_dataset.parquet`. Por lo tanto, las columnas derivadas, codificaciones, agregaciones de reviews, tratamiento de nulos y tipos de datos nacen del mismo proceso usado para entrenar.

Flujo propuesto:

1. El ETL genera `training_dataset.parquet` para entrenamiento.
2. El mismo ETL genera `inference_dataset.json` para inferencia.
3. La API carga la lista de peliculas desde el JSON de inferencia.
4. El usuario elige una pelicula en la interfaz.
5. La API busca esa pelicula en el JSON y toma sus features procesadas.
6. La API elimina columnas que no deben entrar al modelo, como `imdb_rating`.
7. La API valida que las columnas coincidan con las features esperadas por el modelo.
8. El modelo productivo devuelve la prediccion de rating.

Este enfoque ayuda a prevenir training-serving skew porque entrenamiento e inferencia dependen de un mismo pipeline de preparacion de datos. La API queda enfocada en servir el modelo y validar entradas, no en duplicar logica de transformacion.

## 8. Tracking de experimentos y model registry

Para aplicar MLOps, el entrenamiento deberia registrar cada corrida en Weights & Biases.

Informacion a registrar:

- Version del dataset utilizado.
- Parametros del modelo.
- Metricas de entrenamiento y validacion.
- Importancia de features.
- Artefacto del modelo entrenado.

El proyecto ya define una integracion con W&B desde la API:

```text
Entity: mlprod-obli
Project: imdb-rating
Artifact: imdb-rating-model
Alias: production
```

La idea es usar alias para promover modelos:

| Alias | Uso |
| --- | --- |
| `candidate` | Modelo recien entrenado |
| `staging` | Modelo validado para pruebas |
| `production` | Modelo usado por la API |

Esto permite separar entrenamiento de despliegue y controlar que version del modelo esta activa.

### 8.1. Trazabilidad de ML

La trazabilidad permite reconstruir que datos, codigo, parametros y modelo participaron en una prediccion o en una version publicada. En este proyecto se considera versionar tres elementos principales: experimentos, modelos y datos.

| Elemento | Como se versiona | Para que sirve |
| --- | --- | --- |
| Experimentos | Corridas en W&B con parametros, metricas y artefactos asociados | Comparar modelos, justificar la eleccion final y auditar resultados |
| Modelos | Artifacts de W&B con version y aliases como `candidate`, `staging` y `production` | Saber que modelo esta desplegado y poder volver a una version anterior |
| Datos crudos | Archivos Parquet en S3 particionados por fecha y corrida (`run_YYYYMMDD_HHMMSS`) | Identificar de que extraccion provienen los datos usados |
| Dataset procesado | `training_dataset.parquet` generado por el ETL y registrado como artifact o con metadata de corrida | Relacionar cada entrenamiento con el dataset exacto utilizado |
| Datos de inferencia | `inference_dataset.json` generado por el mismo ETL que el dataset de entrenamiento | Asegurar consistencia entre entrenamiento e inferencia |

Para que la trazabilidad sea completa, cada corrida de entrenamiento deberia guardar:

- Identificador o ruta del dataset usado.
- Fecha y version de la corrida del ETL.
- Parametros del modelo.
- Metricas obtenidas.
- Version del codigo o commit de Git.
- Artifact del modelo entrenado.
- Lista de features esperadas por el modelo.

Con esta informacion se puede responder preguntas como: que datos se usaron para entrenar el modelo productivo, que metricas tenia, que features esperaba y que version esta siendo consumida por la API.

## 9. Serving del modelo

La aplicacion de serving esta implementada con FastAPI. Actualmente expone endpoints para:

| Endpoint | Descripcion |
| --- | --- |
| `/` | Interfaz web |
| `/status` | Health check de la aplicacion |
| `/movies` | Lectura de peliculas desde S3 |
| `/model` | Consulta del artifact productivo en W&B |

Como mejora principal, se propone agregar:

| Endpoint | Descripcion |
| --- | --- |
| `POST /predict` | Recibe una pelicula seleccionada o su `imdb_id`, busca sus features en el JSON de inferencia y devuelve el rating estimado |

El endpoint de prediccion deberia cargar el modelo productivo desde W&B, recuperar del JSON de inferencia las features ya procesadas, excluir columnas que no deben usarse como entrada del modelo y devolver una respuesta consistente. Este diseno evita duplicar transformaciones dentro de la API y reduce el riesgo de training-serving skew.

## 10. Containerizacion

La aplicacion se empaqueta con Docker usando una imagen base de Python. El contenedor instala las dependencias, copia la aplicacion FastAPI y expone el puerto 8000.

Esto permite ejecutar el mismo artefacto en local y en produccion, reduciendo diferencias entre ambientes.

Ejecucion local:

```bash
docker compose up --build
```

## 11. Infraestructura como codigo

La infraestructura cloud se define con Terraform. Esto permite versionar los recursos, recrearlos y documentar la arquitectura de despliegue.

Recursos definidos:

- AWS ECS Cluster.
- Task Definition para Fargate.
- ECS Service.
- Application Load Balancer.
- Target Group con health check en `/status`.
- Security Groups.
- CloudWatch Log Group.
- Politica de acceso a S3 para la task.

El despliegue usa una imagen Docker publicada en ECR y luego referenciada desde Terraform.

## 12. Gestion de secretos

La API necesita credenciales para consultar W&B. Para evitar hardcodear secretos, se usa AWS SSM Parameter Store.

Parametros esperados:

```text
wandb-org
wandb-api-key
```

Si no se encuentran en SSM, la aplicacion permite usar variables de entorno como fallback:

```text
WANDB_USER
WANDB_API_KEY
```

Esto aplica una buena practica de seguridad: separar secretos del codigo fuente.

## 13. Observabilidad y monitoreo

La solucion incluye un primer nivel de observabilidad:

- Endpoint `/status` como health check.
- Logs de contenedor enviados a CloudWatch.
- Consulta de version del modelo productivo mediante `/model`.

Mejoras posibles:

- Registrar cantidad de predicciones realizadas.
- Medir latencia del endpoint `/predict`.
- Guardar errores de inferencia.
- Registrar distribucion de features de entrada.
- Detectar drift comparando datos nuevos contra datos de entrenamiento.

## 14. Automatizacion

El proyecto incluye un `Makefile` para automatizar tareas frecuentes.

Comandos relevantes:

```bash
make scraper-install
make scraper-login
make scraper-run
make etl-run
make scraper-etl
make pipeline
```

Esto permite ejecutar el flujo de ingesta y procesamiento de forma mas ordenada y repetible.

## 15. Conceptos de clase aplicados

| Concepto | Aplicacion en el proyecto |
| --- | --- |
| Pipeline de datos | Scraper + S3 + ETL |
| Data lake | S3 como almacenamiento central |
| Versionado de datos | Archivos particionados por fecha y corrida |
| Feature engineering | Generacion de features numericas y categoricas |
| Prevencion de data leakage | Exclusion de variables no disponibles o demasiado cercanas al target |
| Training-serving skew | Uso recomendado de pipeline y schema compartidos entre entrenamiento e inferencia |
| Reproducibilidad | Docker, Terraform, Makefile |
| Tracking de experimentos | W&B para metricas y parametros |
| Model registry | Artifacts y aliases en W&B |
| Trazabilidad de ML | Versionado de experimentos, modelos, datos y features usadas |
| Serving | FastAPI como API de inferencia |
| CI/CD potencial | Build de imagen, push a ECR, deploy con Terraform |
| Gestion de secretos | AWS SSM Parameter Store |
| Observabilidad | Health check y CloudWatch logs |
| Despliegue cloud | ECS Fargate + ALB |

## 16. Trabajo pendiente

Para completar la solucion de punta a punta, quedan pendientes los siguientes puntos:

1. Implementar o documentar el entrenamiento del modelo.
2. Registrar experimentos y modelos en W&B.
3. Promover un modelo con alias `production`.
4. Implementar el endpoint real `POST /predict` usando `imdb_id` y `inference_dataset.json`.
5. Validar que el JSON de inferencia tenga las features esperadas por el modelo y excluir `imdb_rating` antes de predecir.
6. Agregar tests basicos para ETL y API.
7. Documentar metricas finales del modelo.
8. Incluir capturas del despliegue funcionando.

## 17. Conclusiones

El proyecto construye una base solida para una solucion de Machine Learning en Produccion. No solo contempla el modelo, sino tambien los elementos necesarios para operarlo: datos versionados, procesamiento automatizado, empaquetado, infraestructura reproducible, despliegue cloud y registro de modelos.

La principal mejora para cerrar el ciclo MLOps completo es conectar el dataset procesado con un entrenamiento registrado en W&B y exponer predicciones reales desde la API desplegada.
