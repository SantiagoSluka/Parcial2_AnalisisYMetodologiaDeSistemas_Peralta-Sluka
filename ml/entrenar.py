"""Entrenamiento del modelo."""
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

# Orden de columnas
COLUMNAS = ["dias_anticipacion", "es_videoconsulta", "pago_online", "ausencias_previas"]

rng = np.random.default_rng(42)
n = 3000
dias = rng.integers(0, 61, n)
video = (rng.random(n) < 0.25).astype(int)
pago = (rng.random(n) < 0.15).astype(int)
previas = rng.poisson(0.6, n)

# Supuestos del SRS
logit = -2.7 +0.03 * dias + 0.7 * previas - 0.85 * pago + 0.25 * video
ausente = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)

X = np.column_stack([dias, video, pago, previas])
X_train, X_test, y_train, y_test = train_test_split(X, ausente, test_size=0.25, random_state=42, stratify=ausente)
modelo = LogisticRegression().fit(X_train, y_train)

print(f"Ausentismo en los datos: {ausente.mean():.1%}")
print(f"Accuracy (test): {accuracy_score(y_test, modelo.predict(X_test)):.2f}")
print(f"ROC AUC (test):  {roc_auc_score(y_test, modelo.predict_proba(X_test)[:, 1]):.2f}")
print("Coeficientes:", dict(zip(COLUMNAS, modelo.coef_[0].round(3))))

destino = Path(__file__).with_name("modelo_ausentismo.joblib")
joblib.dump(modelo, destino)
print(f"Modelo guardado en {destino}")
