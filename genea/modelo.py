"""Modelo de priorización de mercados de Genea (pipeline del TP3)."""
from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .nombres import PAISES_ES

DATOS = Path(__file__).resolve().parent / "datos"
COMPONENTES = ["mercado", "diversidad_origen", "conectividad", "poblacion", "mayores65_pct"]

NOMBRES_INDICES = {"diversidad_origen": "Diversidad de origen", "conectividad": "Conectividad de apellidos",
                   "mercado": "Mercado"}
NOMBRES_COMPONENTES = {**NOMBRES_INDICES, "poblacion": "Población", "mayores65_pct": "Mayores de 65"}

# Descripción, unidad y rango válido de cada variable de entrada
VARIABLES = {
    "diversidad_origen": {"nombre": "Diversidad de origen de los apellidos", "unidad": "índice 0 a 1", "min": 0, "max": 1},
    "n_familias_relevantes": {"nombre": "Familias de origen con peso en el país", "unidad": "cantidad", "min": 1, "max": 30},
    "cuota_apellidos_transregionales": {"nombre": "Cuota de apellidos presentes en otras regiones", "unidad": "proporción 0 a 1", "min": 0, "max": 1},
    "paises_por_apellido_pond": {"nombre": "Países en los que aparece cada apellido (promedio ponderado)", "unidad": "países", "min": 1, "max": 120},
    "similitud_max": {"nombre": "Afinidad de apellidos con el país más parecido", "unidad": "índice 0 a 1", "min": 0, "max": 1},
    "pbi_pc_ppa": {"nombre": "PBI per cápita (PPA)", "unidad": "US$ internacionales", "min": 100, "max": 300_000},
    "internet_pct": {"nombre": "Población que usa internet", "unidad": "%", "min": 0, "max": 100},
    "urbana_pct": {"nombre": "Población urbana", "unidad": "%", "min": 0, "max": 100},
    "poblacion": {"nombre": "Población", "unidad": "personas", "min": 1_000, "max": 2_000_000_000},
    "mayores65_pct": {"nombre": "Población de 65 años o más", "unidad": "%", "min": 0, "max": 60},
}

INGRESOS_ES = {"Low income": "Ingreso bajo", "Lower middle income": "Ingreso medio bajo",
               "Upper middle income": "Ingreso medio alto", "High income": "Ingreso alto"}
REGIONES_ES = {
    "East Asia & Pacific": "Asia Oriental y Pacífico",
    "Europe & Central Asia": "Europa y Asia Central",
    "Latin America & Caribbean": "América Latina y el Caribe",
    "Middle East, North Africa, Afghanistan & Pakistan": "Medio Oriente, Norte de África, Afganistán y Pakistán",
    "North America": "América del Norte",
    "South Asia": "Asia del Sur",
    "Sub-Saharan Africa": "África subsahariana",
}


class DatosInvalidos(ValueError):
    """Los datos de entrada no se pueden procesar. `detalles` lista cada problema por campo."""

    def __init__(self, mensaje: str, detalles: list[dict] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalles = detalles or []


class NoEncontrado(LookupError):
    """El país o el apellido pedido no existe en los datos."""


@dataclass
class Aviso:
    campo: str
    tipo: str
    mensaje: str

    def a_dict(self) -> dict:
        return {"campo": self.campo, "tipo": self.tipo, "mensaje": self.mensaje}


@dataclass
class PaisPreparado:
    transformadas: dict[str, float]
    avisos: list[Aviso] = field(default_factory=list)
    imputadas: list[str] = field(default_factory=list)
    region: str | None = None


def _clave(texto: str) -> str:
    """Texto en minúsculas, sin acentos ni espacios repetidos (para comparar categorías)."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return " ".join(t.casefold().replace("&", "y").split())


class ModeloGenea:
    """Modelo del TP3 cargado desde el artefacto JSON, más los datos de referencia de los 65 países."""

    def __init__(self, carpeta: Path = DATOS):
        self.art = json.loads((carpeta / "modelo_genea_v1.1.json").read_text(encoding="utf-8"))
        leer = dict(keep_default_na=False, na_values=[""])
        self.paises = pd.read_csv(carpeta / "features_paises.csv", index_col="country_code", **leer)
        self.paises["pais_en"] = self.paises["pais"]
        self.paises["pais"] = [PAISES_ES.get(c, n) for c, n in zip(self.paises.index, self.paises["pais_en"])]
        self.pares = pd.read_csv(carpeta / "pares_afinidad_migracion.csv", **leer)
        self.version = self.art["version"]
        self.variables = self.art["variables_modelo"]
        self.bloques = self.art["bloques"]
        self.centroides = np.asarray(self.art["centroides"])
        self.pesos_base = self.art["pesos_ranking"]
        self.codigos_ref = self.art["paises_entrenamiento"]

        # Categorías aceptadas (en inglés como en el Banco Mundial, o en castellano)
        self._ingresos = {}
        for en, codigo in self.art["orden_ingreso"].items():
            for alias in (en, INGRESOS_ES[en], INGRESOS_ES[en].replace("Ingreso ", "")):
                self._ingresos[_clave(alias)] = en
        self._regiones = {}
        for en in self.art["regiones"]:
            for alias in (en, REGIONES_ES[en]):
                self._regiones[_clave(alias)] = en

        # Referencia: los 65 países del entrenamiento procesados con el mismo pipeline
        ref = self.paises.loc[self.codigos_ref]
        filas = [self._preparar_fila(fila.to_dict(), estricto=False).transformadas for _, fila in ref.iterrows()]
        self.z_ref = self._estandarizar(pd.DataFrame(filas, index=ref.index))
        self.indices_ref = self._indices(self.z_ref)
        self.segmento_ref, self.dist_ref = self._asignar(self.indices_ref)
        self.comp_ref = self._componentes(self.indices_ref, self.z_ref)
        self.ranking_base = self.ranking()


    def _normalizar_ingreso(self, valor, avisos, detalles):
        if valor is None or (isinstance(valor, float) and math.isnan(valor)) or str(valor).strip() == "":
            return None
        en = self._ingresos.get(_clave(valor))
        if en is None:
            validos = ", ".join(INGRESOS_ES.values())
            detalles.append({"campo": "income", "mensaje": f"Nivel de ingreso '{valor}' desconocido. Valores válidos: {validos}."})
        return en

    def _normalizar_region(self, valor, avisos):
        if valor is None or (isinstance(valor, float) and math.isnan(valor)) or str(valor).strip() == "":
            avisos.append(Aviso("region", "region_faltante",
                                "No se indicó la región: los faltantes se imputan con la mediana global de los 65 países."))
            return None
        en = self._regiones.get(_clave(valor))
        if en is None:
            avisos.append(Aviso("region", "region_no_vista",
                                f"La región '{valor}' no está entre las 7 del entrenamiento: los faltantes se imputan con la mediana global."))
        return en

    def _preparar_fila(self, datos: dict, estricto: bool = True) -> PaisPreparado:
        """Pasos 1 a 5 del pipeline para un país. Con estricto=False no valida rangos (datos de referencia)."""
        avisos: list[Aviso] = []
        detalles: list[dict] = []

        # 1. Tipos y rangos
        valores: dict[str, float | None] = {}
        for var, meta in VARIABLES.items():
            v = datos.get(var)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                valores[var] = None
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                detalles.append({"campo": var, "mensaje": f"'{v}' no es un número."})
                continue
            if math.isnan(v):
                valores[var] = None
                continue
            if math.isinf(v) or (estricto and not meta["min"] <= v <= meta["max"]):
                detalles.append({"campo": var, "mensaje": f"{v:g} está fuera del rango válido ({meta['min']:g} a {meta['max']:g} {meta['unidad']})."})
                continue
            valores[var] = v

        # 2. Categorías
        ingreso = self._normalizar_ingreso(datos.get("income"), avisos, detalles)
        region = self._normalizar_region(datos.get("region"), avisos) if estricto else datos.get("region")
        if detalles:
            raise DatosInvalidos("Hay datos inválidos en el país enviado.", detalles)

        # 3. Ingreso ordinal
        valores["ingreso_ordinal"] = None if ingreso is None else float(self.art["orden_ingreso"][ingreso])

        # 4. log1p sobre los valores observados
        for var in self.art["variables_log"]:
            if valores.get(var) is not None:
                valores[var] = float(np.log1p(valores[var]))

        # 5. Imputación: mediana regional y, si no hay región válida, mediana global
        imputadas = []
        for var in self.variables:
            if valores.get(var) is not None:
                continue
            med_region = self.art["medianas_region"][var].get(region) if region else None
            if med_region is not None:
                valores[var] = med_region
                fuente = f"la mediana de {REGIONES_ES.get(region, region)}"
                tipo = "imputado_region"
            else:
                valores[var] = self.art["medianas_global"][var]
                fuente = "la mediana global de los 65 países"
                tipo = "imputado_global"
            imputadas.append(var)
            nombre = "Nivel de ingreso" if var == "ingreso_ordinal" else VARIABLES[var]["nombre"]
            avisos.append(Aviso("income" if var == "ingreso_ordinal" else var, tipo, f"{nombre}: dato faltante, se completó con {fuente}."))

        # Aviso de extrapolación: valores fuera de lo observado en los 65 países
        if estricto:
            ref = self.paises.loc[self.codigos_ref]
            for var in VARIABLES:
                v = datos.get(var)
                if var in imputadas or v in (None, ""):
                    continue
                v = float(v)
                lo, hi = ref[var].min(), ref[var].max()
                if v < lo or v > hi:
                    avisos.append(Aviso(var, "fuera_de_rango_observado",
                                        f"{VARIABLES[var]['nombre']}: {v:g} está fuera de lo observado en el entrenamiento ({lo:g} a {hi:g}); el resultado es una extrapolación."))
        return PaisPreparado({v: valores[v] for v in self.variables}, avisos, imputadas, region)

    def _estandarizar(self, transformadas: pd.DataFrame) -> pd.DataFrame:
        esc = self.art["escalador_variables"]
        media = pd.Series(esc["media"])[self.variables]
        desvio = pd.Series(esc["desvio"])[self.variables]
        return (transformadas[self.variables] - media) / desvio

    def _indices(self, z: pd.DataFrame) -> pd.DataFrame:
        crudos = pd.DataFrame({b: sum(z[v] * s for v, s in vs.items()) / len(vs) for b, vs in self.bloques.items()},
                              index=z.index)
        esc = self.art["escalador_indices"]
        return (crudos - pd.Series(esc["media"])) / pd.Series(esc["desvio"])

    def _asignar(self, indices: pd.DataFrame):
        d = np.sqrt(((indices[list(self.bloques)].to_numpy()[:, None, :] - self.centroides[None]) ** 2).sum(axis=2))
        return pd.Series(d.argmin(axis=1), index=indices.index), pd.DataFrame(d, index=indices.index)

    def _componentes(self, indices: pd.DataFrame, z: pd.DataFrame) -> pd.DataFrame:
        return pd.concat([indices, z[["poblacion", "mayores65_pct"]]], axis=1)[COMPONENTES]


    def validar_pesos(self, pesos: dict | None) -> dict[str, float]:
        if pesos is None:
            return dict(self.pesos_base)
        detalles = []
        desconocidos = set(pesos) - set(COMPONENTES)
        if desconocidos:
            detalles.append({"campo": "pesos", "mensaje": f"Componentes desconocidos: {', '.join(sorted(desconocidos))}. Válidos: {', '.join(COMPONENTES)}."})
        limpio = {}
        for c in COMPONENTES:
            v = pesos.get(c, 0)
            try:
                v = float(v)
            except (TypeError, ValueError):
                detalles.append({"campo": f"pesos.{c}", "mensaje": "debe ser un número."})
                continue
            if math.isnan(v) or v < 0:
                detalles.append({"campo": f"pesos.{c}", "mensaje": "no puede ser negativo."})
            limpio[c] = v
        if not detalles and sum(limpio.values()) <= 0:
            detalles.append({"campo": "pesos", "mensaje": "Al menos un peso tiene que ser mayor a cero."})
        if detalles:
            raise DatosInvalidos("Los pesos enviados no son válidos.", detalles)
        total = sum(limpio.values())
        return {c: v / total for c, v in limpio.items()}

    def ranking(self, pesos: dict | None = None, simulaciones: int | None = None,
                extra: pd.DataFrame | None = None, excluir: str | None = None) -> pd.DataFrame:
        """Puntaje, puesto, sensibilidad y prioridad.

        `extra` agrega países evaluados (sus componentes) y `excluir` saca un país de la
        referencia (para un escenario que lo reemplaza). La escala 0-100 siempre se fija con
        los 65 países del entrenamiento, así un país nuevo puede quedar por encima de 100.
        """
        w = self.validar_pesos(pesos)
        sens = self.art["sensibilidad"]
        n_sim = simulaciones or sens["simulaciones"]
        comp = self.comp_ref if excluir is None else self.comp_ref.drop(index=excluir)
        if extra is not None:
            comp = pd.concat([comp, extra[COMPONENTES]])
        vec = np.array([w[c] for c in COMPONENTES])
        bruto = comp.to_numpy() @ vec
        bruto_ref = self.comp_ref.to_numpy() @ vec
        lo, hi = bruto_ref.min(), bruto_ref.max()
        puntaje = 100 * (bruto - lo) / (hi - lo)

        rng = np.random.default_rng(sens["semilla"])
        alfa = np.maximum(vec, 0.005) * sens["concentracion_dirichlet"]
        W = rng.dirichlet(alfa, size=n_sim)
        puestos = np.argsort(np.argsort(-(comp.to_numpy() @ W.T), axis=0), axis=0) + 1
        top = sens["top"]
        df = pd.DataFrame({"puntaje": puntaje,
                           "puesto_mediano": np.median(puestos, axis=1),
                           "prob_top10": (puestos <= top).mean(axis=1)}, index=comp.index)
        df["puesto"] = df["puntaje"].rank(ascending=False, method="first").astype(int)
        regla = self.art["regla_prioridad"]
        df["prioridad"] = np.where(df["prob_top10"] >= regla["prioridad_1_prob_top10_min"], 1,
                                   np.where(df["puesto_mediano"] <= regla["prioridad_2_puesto_mediano_max"], 2, 3))
        for c in COMPONENTES:
            df[f"aporte_{c}"] = comp[c] * w[c]
        return df.sort_values("puesto")

    def resumen_ranking(self, pesos: dict | None = None, simulaciones: int | None = None) -> dict:
        w = self.validar_pesos(pesos)
        r = self.ranking(w, simulaciones)
        base = self.ranking_base["puesto"].loc[r.index]
        rho = float(np.corrcoef(base.to_numpy(), r["puesto"].to_numpy())[0, 1])
        top_nuevo, top_base = set(r.index[r["puesto"] <= 10]), set(self.ranking_base.index[self.ranking_base["puesto"] <= 10])
        filas = [self._fila_ranking(c, r.loc[c]) for c in r.index]
        for f in filas:
            f["cambio_puesto"] = int(self.ranking_base.loc[f["codigo"], "puesto"] - f["puesto"])
        return {"pesos_normalizados": w, "simulaciones": simulaciones or self.art["sensibilidad"]["simulaciones"],
                "correlacion_con_ranking_base": round(rho, 4),
                "top10_compartido_con_base": len(top_nuevo & top_base),
                "prioridad_1": [f["codigo"] for f in filas if f["prioridad"] == 1],
                "paises": filas}

    def _fila_ranking(self, codigo: str, fila: pd.Series) -> dict:
        seg = int(self.segmento_ref[codigo])
        return {"codigo": codigo, "pais": self.paises.loc[codigo, "pais"], "puesto": int(fila["puesto"]),
                "puntaje": round(float(fila["puntaje"]), 2), "puesto_mediano": float(fila["puesto_mediano"]),
                "prob_top10": round(float(fila["prob_top10"]), 4), "prioridad": int(fila["prioridad"]),
                "segmento": seg, "nombre_segmento": self.art["segmentos"][str(seg)]["nombre"],
                "aportes": {c: round(float(fila[f"aporte_{c}"]), 4) for c in COMPONENTES}}


    def puentes(self, codigo: str, n: int | None = None) -> list[dict]:
        cfg = self.art["puentes"]
        n = n or cfg["cantidad"]
        p = self.pares
        sub = p[(p["pais_a"] == codigo) | (p["pais_b"] == codigo)].copy()
        sub["puente"] = np.where(sub["pais_a"] == codigo, sub["pais_b"], sub["pais_a"])
        sub = sub[sub["similitud_apellidos"] >= cfg["similitud_minima"]].sort_values("similitud_apellidos", ascending=False).head(n)
        nombres = self.paises["pais"]
        return [{"codigo": c, "pais": nombres.get(c, c), "similitud": round(float(s), 3), "migrantes_2024": int(m)}
                for c, s, m in sub[["puente", "similitud_apellidos", "migrantes_2024"]].itertuples(index=False)]

    def segmento_info(self, seg: int) -> dict:
        info = self.art["segmentos"][str(seg)]
        return {"id": seg, **info,
                "centroide": {NOMBRES_INDICES[b]: round(float(v), 3) for b, v in zip(self.bloques, self.centroides[seg])},
                "paises": sorted(self.segmento_ref.index[self.segmento_ref == seg].tolist())}

    def ficha(self, codigo: str) -> dict:
        codigo = str(codigo).upper().strip()
        if codigo not in self.paises.index:
            raise NoEncontrado(f"No hay datos del país '{codigo}'. Usá un código ISO de dos letras, por ejemplo AR.")
        fila = self.paises.loc[codigo]
        if codigo not in self.indices_ref.index:
            return {"codigo": codigo, "pais": fila["pais"], "en_modelo": False,
                    "motivo": "No tiene los indicadores del Banco Mundial que usa el modelo. Se puede evaluar en el simulador con datos imputados.",
                    "region": fila["region"], "region_es": REGIONES_ES.get(fila["region"], fila["region"]),
                    "ingreso": INGRESOS_ES.get(fila["income"]) if not pd.isna(fila["income"]) else None,
                    "variables": {v: (None if pd.isna(fila[v]) else float(fila[v])) for v in VARIABLES},
                    "puentes": self.puentes(codigo)}
        r = self.ranking_base.loc[codigo]
        seg = int(self.segmento_ref[codigo])
        dist = self.dist_ref.loc[codigo].to_numpy()
        return {"codigo": codigo, "pais": fila["pais"], "en_modelo": True, "region": fila["region"],
                "region_es": REGIONES_ES.get(fila["region"], fila["region"]),
                "ingreso": INGRESOS_ES.get(fila["income"], fila["income"]),
                "variables": {v: (None if pd.isna(fila[v]) else float(fila[v])) for v in VARIABLES},
                "origen_imputado": bool(pd.isna(fila["diversidad_origen"])),
                "indices": {b: round(float(self.indices_ref.loc[codigo, b]), 3) for b in self.bloques},
                "segmento": self.segmento_info(seg),
                "distancias_segmentos": self._distancias(dist),
                "ranking": self._fila_ranking(codigo, r),
                "puentes": self.puentes(codigo)}

    def _distancias(self, dist: np.ndarray) -> list[dict]:
        orden = np.argsort(dist)
        return [{"segmento": int(s), "nombre": self.art["segmentos"][str(int(s))]["nombre"], "distancia": round(float(dist[s]), 3)}
                for s in orden]

    def evaluar(self, datos: dict, base_codigo: str | None = None, pesos: dict | None = None) -> dict:
        """Evalúa un país nuevo o un escenario sobre un país existente (los datos enviados pisan los originales)."""
        entrada = {}
        nombre = datos.get("nombre") or "País evaluado"
        if base_codigo:
            base_codigo = base_codigo.upper().strip()
            if base_codigo not in self.paises.index:
                raise NoEncontrado(f"No hay datos del país '{base_codigo}'.")
            fila = self.paises.loc[base_codigo]
            entrada = {k: (None if pd.isna(fila[k]) else fila[k]) for k in [*VARIABLES, "income", "region"]}
            nombre = datos.get("nombre") or f"{fila['pais']} (escenario)"
        for k, v in datos.items():
            if k in VARIABLES or k in ("income", "region"):
                if v is not None:
                    entrada[k] = v
        prep = self._preparar_fila(entrada, estricto=True)
        idx = "__evaluado__"
        z = self._estandarizar(pd.DataFrame([prep.transformadas], index=[idx]))
        ind = self._indices(z)
        seg, dist = self._asignar(ind)
        comp = self._componentes(ind, z)
        w = self.validar_pesos(pesos)
        # Se rankea junto a los 65 países; si es un escenario, reemplaza al país original
        base_r = self.ranking(w) if pesos is not None else self.ranking_base
        reemplaza = base_codigo if base_codigo in self.comp_ref.index else None
        r_todo = self.ranking(w, extra=comp, excluir=reemplaza)
        fila_r = r_todo.loc[idx]
        s = int(seg.iloc[0])
        n_imp = len(prep.imputadas)
        resultado = {
            "nombre": nombre, "base_codigo": base_codigo,
            "indices": {b: round(float(ind.iloc[0][b]), 3) for b in self.bloques},
            "segmento": self.segmento_info(s),
            "distancias_segmentos": self._distancias(dist.iloc[0].to_numpy()),
            "ranking": {"puesto": int(fila_r["puesto"]), "de": int(len(r_todo)), "puntaje": round(float(fila_r["puntaje"]), 2),
                        "puesto_mediano": float(fila_r["puesto_mediano"]), "prob_top10": round(float(fila_r["prob_top10"]), 4),
                        "prioridad": int(fila_r["prioridad"]),
                        "aportes": {c: round(float(fila_r[f"aporte_{c}"]), 4) for c in COMPONENTES}},
            "avisos": [a.a_dict() for a in prep.avisos],
            "variables_imputadas": prep.imputadas,
            "calidad": "alta" if n_imp == 0 else ("media" if n_imp <= 2 else "baja"),
            "puentes": self.puentes(base_codigo) if base_codigo else [],
        }
        if base_codigo and base_codigo in self.ranking_base.index:
            orig = base_r.loc[base_codigo]
            resultado["comparacion_original"] = {
                "segmento": int(self.segmento_ref[base_codigo]),
                "nombre_segmento": self.art["segmentos"][str(int(self.segmento_ref[base_codigo]))]["nombre"],
                "puesto": int(orig["puesto"]), "puntaje": round(float(orig["puntaje"]), 2), "prioridad": int(orig["prioridad"])}
        return resultado

    def descripcion(self) -> dict:
        """Criterios y supuestos del modelo (devolución del TP3): pesos teóricos y efectivos y regla de selección."""
        pesos_vars = []
        for b, vs in self.bloques.items():
            for v in vs:
                pesos_vars.append({"variable": v, "nombre": VARIABLES.get(v, {"nombre": "Nivel de ingreso (ordinal 0 a 3)"})["nombre"],
                                   "indice": NOMBRES_INDICES[b], "peso_en_indice": round(1 / len(vs), 4),
                                   "peso_efectivo_en_puntaje": round(self.pesos_base[b] / len(vs), 4)})
        for v in ("poblacion", "mayores65_pct"):
            pesos_vars.append({"variable": v, "nombre": VARIABLES[v]["nombre"], "indice": "Entra directo al ranking",
                               "peso_en_indice": None, "peso_efectivo_en_puntaje": self.pesos_base[v]})
        return {
            "version": self.version, "origen": self.art["origen"], "fecha_entrenamiento": self.art["fecha_entrenamiento"],
            "paises_entrenamiento": len(self.codigos_ref),
            "pesos_ranking": self.pesos_base, "nombres_componentes": NOMBRES_COMPONENTES,
            "pesos_variables": pesos_vars,
            "variables_entrada": VARIABLES, "variables_log": self.art["variables_log"],
            "niveles_ingreso": list(INGRESOS_ES.values()),
            "regiones": [{"codigo": r, "nombre": REGIONES_ES[r]} for r in self.art["regiones"]],
            "orden_preparacion": [
                "Validar tipos y rangos de cada variable.",
                "Normalizar categorías: ingreso desconocido es un error; región faltante o no vista genera un aviso.",
                "Codificar el nivel de ingreso en escala 0 a 3.",
                "Aplicar log1p a PBI per cápita, población y familias de origen.",
                "Imputar faltantes con la mediana de la región (escala transformada) o, si no hay región válida, con la mediana global.",
                "Estandarizar con la media y el desvío del entrenamiento.",
            ],
            "regla_seleccion_modelo": [
                "63 configuraciones: 3 espacios de variables x 3 algoritmos x k de 2 a 8.",
                "Filtro 1: estabilidad bootstrap (ARI) de 0,7 o más.",
                "Filtro 2: ningún segmento con menos de 5 países.",
                "Entre las que pasan ambos filtros, la de mayor silhouette.",
            ],
            "embudo_seleccion": self.art["seleccion"],
            "regla_prioridad": {
                "1": "Probabilidad de quedar en el top 10 de al menos 50% en 5.000 simulaciones de pesos.",
                "2": "El resto de los países con puesto mediano de 25 o mejor.",
                "3": "El resto (monitorear).",
            },
            "segmentos": [self.segmento_info(s) for s in range(len(self.centroides))],
            "limitaciones": [
                "Estructura de segmentos moderada (silhouette 0,38): los segmentos simplifican un continuo.",
                "La fuente de apellidos sobrerrepresenta a Medio Oriente y fragmenta los apellidos italianos.",
                "Los pesos del ranking son supuestos de negocio.",
                "Validamos conexión entre países, no demanda real de genealogía.",
            ],
        }
