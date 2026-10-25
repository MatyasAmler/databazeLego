"""Detekce problémů v datech z vážení."""
from hlidac.analysis.base import Detector
from hlidac.analysis.crew import CrewQualityDetector
from hlidac.analysis.drift import ScaleDriftDetector
from hlidac.analysis.rampup import RampupDetector
from hlidac.analysis.service import AnalysisResult, AnalysisService, default_detectors

__all__ = [
    "AnalysisResult",
    "AnalysisService",
    "CrewQualityDetector",
    "Detector",
    "RampupDetector",
    "ScaleDriftDetector",
    "default_detectors",
]
