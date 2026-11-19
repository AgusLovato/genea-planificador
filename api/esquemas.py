"""Entradas y salidas de la API (Pydantic). Los rangos válidos los controla genea/, que
devuelve los errores en castellano; acá se definen los tipos y la documentación."""
from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

Numero = Optional[Union[float, str]]


class Pesos(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mercado: float = Field(0.35, description="Peso del índice de mercado")
    diversidad_origen: float = Field(0.20, description="Peso del índice de diversidad de origen")
    conectividad: float = Field(0.15, description="Peso del índice de conectividad de apellidos")
    poblacion: float = Field(0.20, description="Peso de la población (log, estandarizada)")
    mayores65_pct: float = Field(0.10, description="Peso del % de población de 65 años o más")


class PedidoRanking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pesos: Pesos = Field(default_factory=Pesos, description="Se normalizan para que sumen 1")
    simulaciones: int = Field(5000, ge=200, le=20000, description="Simulaciones de pesos para la sensibilidad")


class DatosPais(BaseModel):
    """Variables de un país en sus unidades originales. Cualquier campo puede faltar:
    se imputa con la mediana de la región y se informa en `avisos`."""
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "nombre": "Argentina con más PBI", "region": "América Latina y el Caribe", "income": "Ingreso alto",
        "pbi_pc_ppa": 45000, "internet_pct": 95}})
    nombre: Optional[str] = Field(None, max_length=80)
    region: Optional[str] = Field(None, description="Una de las 7 regiones del Banco Mundial, en inglés o castellano")
    income: Optional[str] = Field(None, description="Ingreso bajo, medio bajo, medio alto o alto")
    diversidad_origen: Numero = Field(None, description="0 a 1")
    n_familias_relevantes: Numero = Field(None, description="1 a 30")
    cuota_apellidos_transregionales: Numero = Field(None, description="0 a 1")
    paises_por_apellido_pond: Numero = Field(None, description="1 a 120")
    similitud_max: Numero = Field(None, description="0 a 1")
    pbi_pc_ppa: Numero = Field(None, description="US$ internacionales, 100 a 300.000")
    internet_pct: Numero = Field(None, description="0 a 100")
    urbana_pct: Numero = Field(None, description="0 a 100")
    poblacion: Numero = Field(None, description="1.000 a 2.000 millones")
    mayores65_pct: Numero = Field(None, description="0 a 60")


class PedidoEvaluar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pais: DatosPais = Field(default_factory=DatosPais)
    base_codigo: Optional[str] = Field(None, description="Código ISO de un país existente para armar un escenario; "
                                                         "los datos enviados pisan los originales")
    pesos: Optional[Pesos] = None


class Error(BaseModel):
    codigo: str
    mensaje: str
    detalles: list[dict] = []


class RespuestaError(BaseModel):
    error: Error
