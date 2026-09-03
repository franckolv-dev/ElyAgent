# =============================================================================
# @project    ELY — Exactly Like You
# @file       backend/scripts/export_gliner_onnx.py
# @brief      Export OFFLINE de urchade/gliner_multi_pii-v1 en ONNX int8 pour
#             la couche 2 NER du SecurityFilter (PII_NER_ENABLED).
#
# @author     Franck OLLIVIER <contact@agent-ely.fr>
# @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
# @license    MIT
#
# Pourquoi un export offline : le chargement PyTorch fp32 pèse 2553 Mo de RSS
# (bench 2026-06-10) — il ne doit JAMAIS avoir lieu dans le conteneur backend
# (cap mémoire 4g, partagé avec l'app vivante). On exporte donc sur l'HÔTE,
# dans un venv dédié (gliner tire torch), vers ./data/pii_ner qui est monté
# dans le conteneur. Le backend ne charge ensuite que l'ONNX int8
# (~500-800 Mo cible, voir app/services/pii_ner.py).
#
# Usage (depuis la racine du repo) :
#   uv venv /tmp/gliner_export_venv --python 3.12
#   uv pip install --python /tmp/gliner_export_venv/bin/python "gliner>=0.2.26" onnx
#   /tmp/gliner_export_venv/bin/python backend/scripts/export_gliner_onnx.py
#
# Produit dans --save_path (défaut ./data/pii_ner/gliner_multi_pii-v1-onnx) :
#   model_quantized.onnx   ← int8, ce que le backend charge
#   gliner_config.json     ← config GLiNER
#   tokenizer.json + …     ← tokenizer (requis par from_pretrained)
# Le model.onnx fp32 intermédiaire (~1.1 Go) est supprimé après validation,
# sauf --keep-fp32.
#
# Ensuite : poser PII_NER_ENABLED=true (+ rebuild avec PII_NER_INSTALL=1 si
# pas déjà fait) et redémarrer le backend.
# =============================================================================
import argparse
import os
import sys

MODEL_ID_DEFAULT = "urchade/gliner_multi_pii-v1"
SAVE_PATH_DEFAULT = os.path.join("data", "pii_ner", "gliner_multi_pii-v1-onnx")

# Doit refléter app/services/pii_ner.py (NER_LABELS / _THRESHOLD) — le script
# tourne dans un venv dédié sans le package app, donc pas d'import direct.
LABELS = ["person", "organization", "address"]
THRESHOLD = 0.5

VALIDATION_TEXT = (
    "Bonjour, je m'appelle Jean Dupont et je travaille chez Capgemini. "
    "Envoyez le contrat à Mme Claire Moreau, 12 rue de la République, 69002 Lyon."
)
# Sous-chaînes qui DOIVENT être couvertes par l'ONNX int8 — si la
# quantization dégradait le rappel au point de les rater, on refuse l'export.
VALIDATION_MUST_DETECT = ["Jean Dupont", "Capgemini", "Claire Moreau", "12 rue de la République"]


def _mb(path: str) -> float:
    return os.path.getsize(path) / (1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export GLiNER PII → ONNX int8 (couche 2 SecurityFilter)")
    parser.add_argument("--model_id", default=MODEL_ID_DEFAULT)
    parser.add_argument("--save_path", default=SAVE_PATH_DEFAULT,
                        help="Répertoire de sortie (monté dans le conteneur via ./data/pii_ner)")
    parser.add_argument("--opset", type=int, default=19)
    parser.add_argument("--keep-fp32", action="store_true",
                        help="Conserver model.onnx fp32 (~1.1 Go) à côté du quantized")
    args = parser.parse_args()

    from gliner import GLiNER  # import lourd (torch) — venv dédié

    print(f"1/4 Chargement PyTorch de {args.model_id} (≈2.5 Go RSS, host only)…")
    model = GLiNER.from_pretrained(args.model_id)
    model.eval()

    os.makedirs(args.save_path, exist_ok=True)
    print(f"2/4 Export ONNX + quantization int8 → {args.save_path}")
    paths = model.export_to_onnx(
        save_dir=args.save_path,
        onnx_filename="model.onnx",
        quantized_filename="model_quantized.onnx",
        quantize=True,
        opset=args.opset,
    )
    quantized_path = paths.get("quantized_path")
    if not quantized_path or not os.path.exists(quantized_path):
        print("ERREUR : la quantization n'a pas produit model_quantized.onnx", file=sys.stderr)
        return 1
    print(f"    model.onnx           : {_mb(paths['onnx_path']):7.0f} Mo")
    print(f"    model_quantized.onnx : {_mb(quantized_path):7.0f} Mo")

    print("3/4 Validation de l'ONNX int8 (mêmes labels/seuil que la prod)…")
    onnx_model = GLiNER.from_pretrained(
        args.save_path,
        load_onnx_model=True,
        onnx_model_file="model_quantized.onnx",
        local_files_only=True,
        map_location="cpu",
    )
    entities = onnx_model.predict_entities(VALIDATION_TEXT, LABELS, threshold=THRESHOLD)
    for e in entities:
        print(f"    {e['label']:<13} {e['score']:.2f}  {e['text']!r}")
    covered = [n for n in VALIDATION_MUST_DETECT
               if any(n in e["text"] or e["text"] in n for e in entities)]
    missed = [n for n in VALIDATION_MUST_DETECT if n not in covered]
    if missed:
        print(f"ERREUR : l'int8 rate {missed} — export rejeté (la quantization a "
              f"trop dégradé le rappel ; réessayer avec --opset 14 ou garder fp32).", file=sys.stderr)
        return 1

    if not args.keep_fp32:
        os.remove(paths["onnx_path"])
        print("    model.onnx fp32 supprimé (--keep-fp32 pour le conserver)")

    print("4/4 OK. Prochaines étapes :")
    print("    - PII_NER_ENABLED=true dans .env (+ PII_NER_INSTALL=1 si le package")
    print("      gliner n'est pas encore dans l'image → docker compose build backend)")
    print("    - docker compose up -d backend")
    print(f"    - le backend chargera {os.path.join(args.save_path, 'model_quantized.onnx')}")
    print("      (monté sur /app/.cache/pii_ner/gliner_multi_pii-v1-onnx)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
