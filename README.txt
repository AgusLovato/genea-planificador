GENEA - PLANIFICADOR DE EXPANSIÓN

Entrega 04 de Ciencia de Datos Aplicada (ITBA): despliegue del modelo de priorización de mercados por apellidos.
Equipo: Francisco Varela, Milagros de Ezcurra y Agustín Lovato.

App online: https://genea-planificador.onrender.com
API documentada: https://genea-planificador.onrender.com/docs
(plan gratuito de Render: si estuvo un rato sin uso, la primera carga tarda alrededor de un minuto)

El servicio toma el modelo entrenado en el TP3 (k-means con 5 segmentos sobre tres índices, ranking con
sensibilidad a los pesos y países puente) y lo expone como una API REST con una interfaz web que la consume.
No se reentrena nada: el servicio reproduce exactamente los segmentos, puntajes y prioridades del TP3
(lo verifican los tests).


PANTALLAS

- Dónde entrar (POST /api/ranking): mover los pesos del ranking y ver cómo cambian el orden, la robustez
  y las prioridades.
- Ficha de país (GET /api/paises/{codigo}): segmento, estrategia de entrada, índices, por qué está en ese
  puesto y países puente.
- ¿Qué pasa si...? (POST /api/evaluar): cambiar datos de un país o cargar uno nuevo; lo que falta se imputa
  y se avisa.
- Mercados parecidos (GET /api/similares/{codigo}): para cualquier empresa, los mercados más parecidos a su
  país por perfil del consumidor y cercanía cultural, con el motivo de cada uno.
- Tu apellido (GET /api/apellidos/{apellido}): en qué países aparece un apellido y cuáles son prioritarios
  para Genea.
- Cómo funciona (GET /api/modelo): pesos de cada variable, selección del modelo, reglas y limitaciones.

Todas las entradas y salidas están documentadas en /docs una vez levantado el servicio.


ESTRUCTURA

genea/            lógica del modelo, sin nada de HTTP
  modelo.py       pipeline, ranking, sensibilidad, países puente, evaluación de países nuevos
  apellidos.py    buscador de apellidos
  similares.py    mercados parecidos a un país de origen
  datos/          artefacto del modelo (JSON), datos de los países, pares ONU y apellidos
api/              API (FastAPI): esquemas, endpoints y manejo de errores
web/              interfaz (HTML, CSS y JavaScript) que solo habla con la API
tests/            tests del modelo (paridad con el TP3, datos nuevos) y de la API
scripts/          exportar_artefacto.py: pasa el joblib del TP3 al artefacto JSON
docs/             resultados del TP3 usados como referencia en los tests


CÓMO CORRERLO

Necesita Python 3.11 o más nuevo.

  python -m venv .venv
  source .venv/bin/activate          (en Windows: .venv\Scripts\activate)
  pip install -r requirements.txt
  uvicorn api.main:app --reload

Abrir http://localhost:8000 (interfaz) o http://localhost:8000/docs (API).

Tests:

  pip install -r requirements-dev.txt
  pytest

Con Docker:

  docker build -t genea .
  docker run -p 8000:8000 genea


EJEMPLOS DE LA API

  Ficha de Argentina:
  curl http://localhost:8000/api/paises/AR

  Los 5 mercados más parecidos a Argentina (peso_cultura: 0 solo perfil, 1 solo cultura):
  curl "http://localhost:8000/api/similares/AR?peso_cultura=0.5&n=5"

  Escenario: Argentina con más PBI e internet (solo se envía lo que cambia):
  curl -X POST http://localhost:8000/api/evaluar -H "Content-Type: application/json" -d '{"base_codigo": "AR", "pais": {"pbi_pc_ppa": 45000, "internet_pct": 95}}'

Los errores vuelven siempre con la misma forma, en castellano y por campo. Por ejemplo, con internet en 140:
"140 está fuera del rango válido (0 a 100 %)."


DATOS NUEVOS: ORDEN DE PREPARACIÓN

1. Validar tipos y rangos de cada variable (un valor fuera de rango es un error 422).
2. Normalizar categorías: un nivel de ingreso desconocido es un error; una región faltante o que no estaba
   entre las 7 del entrenamiento genera un aviso.
3. Codificar el ingreso en escala ordinal (0 a 3).
4. Aplicar log1p a PBI per cápita, población y familias de origen.
5. Imputar faltantes con la mediana de la región (en la escala transformada, igual que en el TP3); si la
   región falta o no se vio, con la mediana global de los 65 países. Cada imputación vuelve como aviso.
6. Estandarizar con la media y el desvío del entrenamiento.


DEPLOY

Está publicado en Render con Docker a partir de render.yaml. En el plan gratuito el servicio se duerme tras
15 minutos sin uso y tarda alrededor de un minuto en despertar.

Para regenerar el artefacto desde el TP3:

  python scripts/exportar_artefacto.py --tp3 RUTA/AL/TP3_Modelado
