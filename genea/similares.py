"""Mercados parecidos: para una empresa de cualquier rubro que ya opera en un país y quiere
llevar su producto a otros, busca los países más parecidos al suyo.

El parecido combina dos partes:
  - Perfil del consumidor: nivel de ingreso, PBI per cápita, uso de internet, población urbana y
    peso de los mayores de 65. Se comparan las variables ya estandarizadas por el pipeline del
    TP3 (mismas medias y desvíos), así que una diferencia de 1 equivale a un desvío entre los 65
    países. El parecido es exp(-d), con d la distancia cuadrática media entre los dos países.
  - Cercanía cultural: afinidad de apellidos entre los dos países (la misma de los países puente)
    y vínculo migratorio (migrantes entre ambos según la ONU 2024, en escala logarítmica y
    dividido por el par con más migrantes de la base).

El peso de cada parte lo elige el usuario. La población no entra en el parecido: se informa
como tamaño de mercado, porque un país más chico o más grande puede ser igual de parecido.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .modelo import INGRESOS_ES, REGIONES_ES, DatosInvalidos, ModeloGenea, NoEncontrado

# Variables del perfil, con cómo se leen en castellano
PERFIL = {
    "ingreso_ordinal": "nivel de ingreso",
    "pbi_pc_ppa": "PBI per cápita",
    "internet_pct": "uso de internet",
    "urbana_pct": "población urbana",
    "mayores65_pct": "peso de los mayores de 65",
}
PESO_APELLIDOS = 0.6   # dentro de la cercanía cultural
PESO_MIGRACION = 0.4
# Cómo se lee cada diferencia: (destino más alto, destino más bajo)
LECTURAS = {
    "ingreso_ordinal": ("Nivel de ingreso más alto", "Nivel de ingreso más bajo"),
    "pbi_pc_ppa": ("PBI per cápita más alto", "PBI per cápita más bajo"),
    "internet_pct": ("Más uso de internet", "Menos uso de internet"),
    "urbana_pct": ("Más población urbana", "Menos población urbana"),
    "mayores65_pct": ("Población más envejecida", "Población más joven"),
}
UMBRAL_PARECIDO = 0.5  # diferencia en desvíos hasta la que una variable se considera parecida


def _texto_valor(variable: str, valor) -> str:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "s/d"
    if variable == "pbi_pc_ppa":
        return f"US$ {valor:,.0f}".replace(",", ".")
    if variable == "ingreso_ordinal":
        return INGRESOS_ES.get(valor, str(valor)).replace("Ingreso ", "").lower()
    return f"{valor:.1f}%".replace(".", ",")


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class BuscadorSimilares:
    """Busca los mercados más parecidos a un país de origen entre los 65 del modelo."""

    def __init__(self, modelo: ModeloGenea):
        self.m = modelo
        self.codigos = list(modelo.codigos_ref)
        self.z = modelo.z_ref.loc[self.codigos, list(PERFIL)]
        p = modelo.pares
        self.max_log_migrantes = float(np.log1p(p["migrantes_2024"].max()))
        # Matriz simétrica de afinidad de apellidos y de migrantes entre pares
        ap = p.pivot_table(index="pais_a", columns="pais_b", values="similitud_apellidos")
        mi = p.pivot_table(index="pais_a", columns="pais_b", values="migrantes_2024")
        todos = sorted(set(p["pais_a"]) | set(p["pais_b"]))
        ap = ap.reindex(index=todos, columns=todos)
        mi = mi.reindex(index=todos, columns=todos)
        self.apellidos = ap.combine_first(ap.T).fillna(0.0)
        self.migrantes = mi.combine_first(mi.T).fillna(0.0)

    def _origen(self, codigo: str) -> str:
        codigo = str(codigo).upper().strip()
        if codigo not in self.m.paises.index:
            raise NoEncontrado(f"No hay datos del país '{codigo}'. Usá un código ISO de dos letras, por ejemplo AR.")
        if codigo not in self.codigos:
            raise NoEncontrado(f"{self.m.paises.loc[codigo, 'pais']} no tiene los indicadores del Banco Mundial necesarios "
                               "para comparar su perfil. Elegí uno de los 65 países del modelo.")
        return codigo

    def _valores(self, codigo: str) -> dict:
        fila = self.m.paises.loc[codigo]
        return {"ingreso_ordinal": fila["income"], "pbi_pc_ppa": float(fila["pbi_pc_ppa"]),
                "internet_pct": float(fila["internet_pct"]), "urbana_pct": float(fila["urbana_pct"]),
                "mayores65_pct": float(fila["mayores65_pct"])}

    def buscar(self, codigo: str, peso_cultura: float = 0.5, n: int = 10) -> dict:
        origen = self._origen(codigo)
        if not 0 <= peso_cultura <= 1:
            raise DatosInvalidos("El peso de la cercanía cultural tiene que estar entre 0 y 1.",
                                 [{"campo": "peso_cultura", "mensaje": f"{peso_cultura} está fuera del rango válido (0 a 1)"}])
        if not 1 <= n <= len(self.codigos) - 1:
            raise DatosInvalidos("La cantidad de mercados tiene que estar entre 1 y 64.",
                                 [{"campo": "n", "mensaje": f"{n} está fuera del rango válido (1 a 64)"}])

        otros = [c for c in self.codigos if c != origen]
        dif = self.z.loc[otros] - self.z.loc[origen]
        distancia = np.sqrt((dif ** 2).mean(axis=1))
        perfil = np.exp(-distancia)
        apellidos = self.apellidos.reindex(index=[origen], columns=otros).iloc[0].fillna(0.0)
        migrantes = self.migrantes.reindex(index=[origen], columns=otros).iloc[0].fillna(0.0)
        vinculo = np.log1p(migrantes) / self.max_log_migrantes
        cultura = PESO_APELLIDOS * apellidos + PESO_MIGRACION * vinculo
        total = (1 - peso_cultura) * perfil + peso_cultura * cultura

        tabla = pd.DataFrame({"total": total, "perfil": perfil, "cultura": cultura, "apellidos": apellidos,
                              "migrantes": migrantes}).sort_values("total", ascending=False)
        tabla["puesto"] = range(1, len(tabla) + 1)
        v_origen = self._valores(origen)
        mercados = [self._mercado(c, fila, dif.loc[c], v_origen) for c, fila in tabla.head(n).iterrows()]

        fila_o = self.m.paises.loc[origen]
        return {
            "origen": {"codigo": origen, "pais": fila_o["pais"],
                       "region_es": REGIONES_ES.get(fila_o["region"], fila_o["region"]),
                       "poblacion": int(fila_o["poblacion"]),
                       "perfil": {v: {"nombre": PERFIL[v], "valor": _texto_valor(v, x)} for v, x in v_origen.items()}},
            "peso_cultura": round(peso_cultura, 3),
            "pesos": {"perfil": round(1 - peso_cultura, 3), "cultura": round(peso_cultura, 3)},
            "candidatos": len(otros),
            "mercados": mercados,
            "metodo": [
                "Perfil del consumidor: nivel de ingreso, PBI per cápita, uso de internet, población urbana y peso de "
                "los mayores de 65, estandarizados como en el modelo del TP3. Parecido = exp(-distancia).",
                f"Cercanía cultural: {PESO_APELLIDOS:.0%} afinidad de apellidos y {PESO_MIGRACION:.0%} vínculo migratorio "
                "(migrantes entre ambos países, ONU 2024, en escala logarítmica).",
                "La población no entra en el parecido: se muestra como tamaño del mercado.",
            ],
        }

    def _mercado(self, codigo: str, fila: pd.Series, dif: pd.Series, v_origen: dict) -> dict:
        info = self.m.paises.loc[codigo]
        v_dest = self._valores(codigo)
        comparacion, en_comun, diferencias = [], [], []
        for var, nombre in PERFIL.items():
            d = float(dif[var])
            lectura = "parecido" if abs(d) <= UMBRAL_PARECIDO else ("más alto" if d > 0 else "más bajo")
            comparacion.append({"variable": var, "nombre": nombre, "origen": _texto_valor(var, v_origen[var]),
                                "destino": _texto_valor(var, v_dest[var]), "diferencia_desvios": round(d, 2),
                                "lectura": lectura})
            if lectura == "parecido":
                en_comun.append(nombre)
            else:
                texto = LECTURAS[var][0 if d > 0 else 1]
                diferencias.append((abs(d), f"{texto}: {_texto_valor(var, v_dest[var])} contra {_texto_valor(var, v_origen[var])}."))

        razones = []
        if en_comun:
            razones.append("Perfil parecido en " + (", ".join(en_comun[:-1]) + " y " + en_comun[-1] if len(en_comun) > 1 else en_comun[0]) + ".")
        ap, mig = float(fila["apellidos"]), int(fila["migrantes"])
        if ap >= 0.5:
            razones.append(f"Comparten muchos apellidos (afinidad {ap:.2f}).".replace(".", ",", 1))
        elif ap >= 0.2:
            razones.append(f"Comparten parte de sus apellidos (afinidad {ap:.2f}).".replace(".", ",", 1))
        if mig >= 10_000:
            razones.append(f"{_miles(mig)} migrantes entre ambos países (ONU 2024).")

        return {
            "puesto": int(fila["puesto"]), "codigo": codigo, "pais": info["pais"],
            "region_es": REGIONES_ES.get(info["region"], info["region"]),
            "parecido": round(100 * float(fila["total"]), 1),
            "perfil": round(100 * float(fila["perfil"]), 1),
            "cultura": round(100 * float(fila["cultura"]), 1),
            "similitud_apellidos": round(ap, 3), "migrantes_2024": mig,
            "poblacion": int(info["poblacion"]), "pbi_pc_ppa": round(float(info["pbi_pc_ppa"]), 0),
            "comparacion": comparacion,
            "razones": razones,
            "a_tener_en_cuenta": ([f"Pocos apellidos en común (afinidad {ap:.2f}): puede haber otro idioma o cultura.".replace(".", ",", 1)]
                                  if ap < 0.2 else []) + [t for _, t in sorted(diferencias, reverse=True)[:2]],
        }
