# Genea · Planificador de expansión

Entrega 04 de Ciencia de Datos Aplicada (ITBA): despliegue del modelo de priorización de mercados por apellidos.
Equipo: Francisco Varela, Milagros de Ezcurra y Agustín Lovato.

**App online:** https://genea-planificador.onrender.com · **API documentada:** https://genea-planificador.onrender.com/docs
(plan gratuito de Render: si estuvo un rato sin uso, la primera carga tarda alrededor de un minuto).

El servicio toma el modelo entrenado en el TP3 (k-means con 5 segmentos sobre tres índices, ranking con
sensibilidad a los pesos y países puente) y lo expone como una API REST con una interfaz web que la consume.
No se reentrena nada: el servicio reproduce exactamente los segmentos, puntajes y prioridades del TP3
(lo verifican los tests).

## Qué se puede hacer

| Pantalla | Para qué sirve | Endpoint que usa |
|---|---|---|
| Dónde entrar | Mover los pesos del ranking y ver cómo cambian el orden, la robustez y las prioridades | `POST /api/ranking` |
| Ficha de país | Segmento, estrategia de entrada, índices, por qué está en ese puesto y países puente | `GET /api/paises/{codigo}` |
| ¿Qué pasa si…? | Cambiar datos de un país o cargar uno nuevo; lo que falta se imputa y se avisa | `POST /api/evaluar` |
| Tu apellido | En qué países aparece un apellido y cuáles son prioritarios para Genea | `GET /api/apellidos/{apellido}` |
| Cómo funciona | Pesos teóricos de cada variable, embudo de selección del modelo, reglas y limitaciones | `GET /api/modelo` |

La documentación interactiva de todas las entradas y salidas está en `/docs` (Swagger) una vez levantado el servicio.

## Estructura

```
genea/            lógica del modelo, sin nada de HTTP
  modelo.py       pipeline, ranking, sensibilidad, países puente, evaluación de países nuevos
  apellidos.py    buscador de apellidos
  datos/          artefacto del modelo (JSON), datos de los países, pares ONU y apellidos
api/              capa de servicio (FastAPI): esquemas, endpoints y manejo de errores
web/              interfaz (HTML, CSS y JavaScript) que solo habla con la API
tests/            tests del modelo (paridad con el TP3, datos nuevos) y de la API
scripts/          exportar_artefacto.py: pasa el joblib del TP3 al artefacto JSON
docs/             resultados del TP3 usados como referencia en los tests
```

## Correrlo en la computadora

Necesita Python 3.11 o más nuevo.

```bash
python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --reload
```

Abrir http://localhost:8000 (interfaz) o http://localhost:8000/docs (API).

Tests:

```bash
pip install -r requirements-dev.txt
pytest
```

Con Docker: `docker build -t genea . && docker run -p 8000:8000 genea`.

## Ejemplos de uso de la API

```bash
# Ficha de Argentina
curl http://localhost:8000/api/paises/AR

# Ranking con pesos propios (se normalizan para que sumen 1)
curl -X POST http://localhost:8000/api/ranking -H "Content-Type: application/json" \
  -d '{"pesos": {"mercado": 0.6, "diversidad_origen": 0.1, "conectividad": 0.05, "poblacion": 0.2, "mayores65_pct": 0.05}}'

# Escenario: Argentina con más PBI e internet (solo se envía lo que cambia)
curl -X POST http://localhost:8000/api/evaluar -H "Content-Type: application/json" \
  -d '{"base_codigo": "AR", "pais": {"pbi_pc_ppa": 45000, "internet_pct": 95}}'
```

Los errores siempre tienen la misma forma, en castellano y por campo:

```json
{"error": {"codigo": "datos_invalidos", "mensaje": "Hay datos inválidos en el país enviado.",
           "detalles": [{"campo": "internet_pct", "mensaje": "140 está fuera del rango válido (0 a 100 %)."}]}}
```

## Datos nuevos: orden de preparación

Responde al punto de la devolución del TP3 sobre categorías faltantes o no vistas.

1. Validar tipos y rangos de cada variable (un valor fuera de rango es un error 422).
2. Normalizar categorías: un nivel de ingreso desconocido es un error; una región faltante o que no estaba
   entre las 7 del entrenamiento genera un aviso.
3. Codificar el ingreso en escala ordinal (0 a 3).
4. Aplicar log1p a PBI per cápita, población y familias de origen.
5. Imputar faltantes con la mediana de la región del país (en la escala ya transformada, igual que en el TP3);
   si la región falta o no se vio, con la mediana global de los 65 países. Cada imputación vuelve como aviso,
   y la respuesta trae una calidad (alta, media o baja) según cuántas variables se imputaron.
6. Estandarizar con la media y el desvío del entrenamiento. Si un valor está fuera de lo observado en los
   65 países, se avisa que el resultado es una extrapolación.

## Publicarlo en internet (Render)

1. Crear una cuenta en GitHub y un repositorio vacío (por ejemplo `genea-planificador`).
2. Subir esta carpeta:
   ```bash
   git remote add origin https://github.com/USUARIO/genea-planificador.git
   git push -u origin main
   ```
3. Crear una cuenta en https://render.com con el usuario de GitHub.
4. En Render: New > Blueprint, elegir el repositorio. Render lee `render.yaml` y crea el servicio con Docker.
5. Cuando termina el deploy, la app queda en `https://genea-planificador.onrender.com` (o el nombre que asigne Render).

En el plan gratuito el servicio se duerme tras 15 minutos sin uso y tarda alrededor de un minuto en despertar:
conviene abrirlo unos minutos antes de la presentación.

## Regenerar el artefacto desde el TP3

```bash
pip install -r requirements-dev.txt
python scripts/exportar_artefacto.py --tp3 RUTA/AL/TP3_Modelado
```

El script lee `modelos/modelo_genea.joblib` del TP3 y escribe `genea/datos/modelo_genea_v1.1.json` con números
puros (medias, desvíos, centroides, medianas y pesos), así el servicio no depende de la versión de scikit-learn.
