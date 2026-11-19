"""Capa de servicio: expone el modelo de Genea como API REST y sirve la interfaz web.

Arranque local:  uvicorn api.main:app --reload
Documentación interactiva de entradas y salidas: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from genea import BuscadorApellidos, DatosInvalidos, ModeloGenea, NoEncontrado

from .esquemas import PedidoEvaluar, PedidoRanking, RespuestaError

log = logging.getLogger("genea.api")
WEB = Path(__file__).resolve().parents[1] / "web"
ESTADO: dict = {}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    modelo = ModeloGenea()
    ESTADO["modelo"] = modelo
    ESTADO["apellidos"] = BuscadorApellidos(modelo)
    log.info("Modelo %s cargado: %d países", modelo.version, len(modelo.codigos_ref))
    yield
    ESTADO.clear()


app = FastAPI(
    title="Planificador de expansión Genea",
    version="1.1",
    description="API del modelo de priorización de mercados por apellidos (Ciencia de Datos Aplicada, ITBA). "
                "Segmenta países, arma el ranking de mercados con su sensibilidad a los pesos, "
                "evalúa países nuevos o escenarios y busca en qué países aparece un apellido.",
    lifespan=ciclo_de_vida,
    responses={404: {"model": RespuestaError}, 422: {"model": RespuestaError}},
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


def error(status: int, codigo: str, mensaje: str, detalles=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []}})


@app.exception_handler(DatosInvalidos)
async def _datos_invalidos(_: Request, exc: DatosInvalidos):
    return error(422, "datos_invalidos", exc.mensaje, exc.detalles)


@app.exception_handler(NoEncontrado)
async def _no_encontrado(_: Request, exc: NoEncontrado):
    return error(404, "no_encontrado", str(exc))


@app.exception_handler(RequestValidationError)
async def _validacion(_: Request, exc: RequestValidationError):
    traduccion = {"float_parsing": "debe ser un número", "float_type": "debe ser un número", "int_parsing": "debe ser un número entero",
                  "extra_forbidden": "campo desconocido", "string_too_long": "texto demasiado largo",
                  "greater_than_equal": "valor demasiado bajo", "less_than_equal": "valor demasiado alto",
                  "json_invalid": "el cuerpo no es un JSON válido", "missing": "campo obligatorio"}
    detalles = []
    for e in exc.errors():
        campo = ".".join(str(p) for p in e.get("loc", []) if p not in ("body",))
        detalles.append({"campo": campo or "cuerpo", "mensaje": traduccion.get(e.get("type"), e.get("msg", "valor inválido"))})
    return error(422, "pedido_invalido", "El pedido no tiene el formato esperado.", detalles)


@app.exception_handler(Exception)
async def _inesperado(_: Request, exc: Exception):
    log.exception("Error inesperado")
    return error(500, "error_interno", "Ocurrió un error inesperado en el servicio.")


def M() -> ModeloGenea:
    return ESTADO["modelo"]


# ---------------------------------------------------------------- endpoints

@app.get("/api/health", tags=["servicio"], summary="Estado del servicio")
def health():
    return {"estado": "ok", "version_modelo": M().version, "paises": len(M().codigos_ref)}


@app.get("/api/modelo", tags=["modelo"], summary="Criterios y supuestos del modelo",
         description="Pesos del ranking, peso teórico de cada variable dentro de su índice y en el puntaje, "
                     "orden de preparación de datos nuevos, regla de selección del modelo y regla de prioridad.")
def modelo():
    return M().descripcion()


@app.get("/api/paises", tags=["países"], summary="Ranking base de los 65 países")
def paises(prioridad: int | None = Query(None, ge=1, le=3), segmento: int | None = Query(None, ge=0, le=4)):
    filas = M().resumen_ranking()["paises"]
    if prioridad:
        filas = [f for f in filas if f["prioridad"] == prioridad]
    if segmento is not None:
        filas = [f for f in filas if f["segmento"] == segmento]
    return {"cantidad": len(filas), "paises": filas}


@app.get("/api/paises/{codigo}", tags=["países"], summary="Ficha de un país",
         description="Segmento y estrategia de entrada, índices, puesto y prioridad, aporte de cada componente y países puente.")
def ficha(codigo: str):
    return M().ficha(codigo)


@app.post("/api/ranking", tags=["ranking"], summary="Ranking con pesos propios",
          description="Recalcula puntajes, sensibilidad (simulaciones de Dirichlet alrededor de los pesos) y prioridades.")
def ranking(pedido: PedidoRanking):
    return M().resumen_ranking(pedido.pesos.model_dump(), pedido.simulaciones)


@app.post("/api/evaluar", tags=["simulador"], summary="Evaluar un país nuevo o un escenario",
          description="Recibe variables en unidades originales. Con `base_codigo` parte de un país existente y "
                      "reemplaza solo lo enviado. Devuelve índices, segmento, puesto hipotético, prioridad y avisos de imputación.")
def evaluar(pedido: PedidoEvaluar):
    datos = pedido.pais.model_dump(exclude_none=True)
    pesos = pedido.pesos.model_dump() if pedido.pesos else None
    return M().evaluar(datos, base_codigo=pedido.base_codigo, pesos=pesos)


@app.get("/api/apellidos", tags=["apellidos"], summary="Sugerencias de apellidos")
def sugerencias(q: str = Query(..., min_length=2, max_length=60)):
    return {"sugerencias": ESTADO["apellidos"].sugerencias(q)}


@app.get("/api/apellidos/{apellido}", tags=["apellidos"], summary="En qué países aparece un apellido")
def apellido(apellido: str):
    try:
        return ESTADO["apellidos"].buscar(apellido)
    except NoEncontrado as e:
        return error(404, "no_encontrado", str(e), [{"campo": "apellido", "sugerencias": ESTADO["apellidos"].sugerencias(apellido)}])
    except ValueError as e:
        return error(422, "datos_invalidos", str(e))


# ---------------------------------------------------------------- interfaz web

@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
