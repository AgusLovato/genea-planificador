"""Planificador de expansión de Genea: lógica del modelo (sin dependencias de la API)."""
from .modelo import COMPONENTES, DatosInvalidos, ModeloGenea, NoEncontrado
from .apellidos import BuscadorApellidos

__all__ = ["ModeloGenea", "BuscadorApellidos", "DatosInvalidos", "NoEncontrado", "COMPONENTES"]
