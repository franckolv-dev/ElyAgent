# Bench scenario C — no-op baseline
#
# Script minimal qui n'appelle AUCUN tool. Mesure le surcoût pur du
# sandbox : démarrage subprocess, génération stubs, environnement
# scrubbé, RPC server lancé pour rien, cleanup. Sert de plancher pour
# normaliser les autres mesures (« scenario A prend X secondes dont
# Y de surcoût sandbox »).
#
# Tools utilisés : 0
print("baseline ok")
print("no tools dispatched")
