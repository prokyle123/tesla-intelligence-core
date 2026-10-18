"""Experimental model discovery metadata, not model weight exchange.

Safe first step towards GHOST fleet model research: only allowlisted
non-identifying performance summaries. Artifact files (.pt/.pkl/.pickle,
ONNX and safetensors) are NOT uploaded, loaded, or promoted.
"""
from __future__ import annotations
import math

SCHEMA="ghost-hive-model-manifest-v1"
KEYS=frozenset(("schema","family","backend","validation_rows","mae","mae_unit",
                "evaluation","version"))
FAMILIES={
    "pack_temp_60m":("C",),
    "pack_temp_180m":("C",),
    "trip_soc_drop":("soc_pp",),
    "trip_energy_kwh":("kwh",),
}
BACKENDS=frozenset(("tree","pytorch"))
VERSIONS=frozenset(("ghost-v1",))
EVALUATIONS=frozenset(("out_of_time_historical",))

class ModelMetadataError(ValueError):pass

def validate_model_manifest(body:object)->dict:
    if not isinstance(body,dict) or set(body)!=KEYS:
        raise ModelMetadataError("Only allowlisted model metadata allowed")
    if body["schema"]!=SCHEMA or body["version"] not in VERSIONS:
        raise ModelMetadataError("Unsupported schema/feature contract")
    if body["family"] not in FAMILIES or body["backend"] not in BACKENDS:
        raise ModelMetadataError("Unsupported family or backend")
    if body["mae_unit"] not in FAMILIES[body["family"]]:
        raise ModelMetadataError("Wrong metric units")
    if body["evaluation"] not in EVALUATIONS:
        raise ModelMetadataError("Only bounded historical research summaries supported")
    if type(body["validation_rows"]) is not int or not 100<=body["validation_rows"]<=1000000:
        raise ModelMetadataError("Insufficient independent validation")
    if type(body["mae"]) not in (int,float):
        raise ModelMetadataError("Invalid score")
    err=float(body["mae"])
    if not math.isfinite(err) or not 0<=err<=100 or abs(err-round(err,3))>.000001:
        raise ModelMetadataError("Invalid or over-precise score")
    return {"schema":SCHEMA,"family":body["family"],"backend":body["backend"],
            "validation_rows":body["validation_rows"],"mae":round(err,3),
            "mae_unit":body["mae_unit"],"evaluation":body["evaluation"],
            "version":body["version"]}
