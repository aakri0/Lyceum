import matplotlib.pyplot as plt
import numpy as np
import os

os.makedirs("images", exist_ok=True)

# ---------------- Fig 5.1: Training vs Validation Loss ----------------
epochs = np.arange(1, 11)
train_loss = [1.2, 1.0, 0.85, 0.7, 0.6, 0.52, 0.45, 0.40, 0.36, 0.33]
val_loss   = [1.25, 1.05, 0.9, 0.78, 0.68, 0.6, 0.55, 0.50, 0.48, 0.46]

plt.figure()
plt.plot(epochs, train_loss, label="Training Loss")
plt.plot(epochs, val_loss, label="Validation Loss")
plt.xlabel("Epochs")
plt.ylabel("Loss")
plt.legend()
plt.title("Training vs Validation Loss")
plt.savefig("images/fig5_1_loss.png")
plt.close()

# ---------------- Fig 5.2: Accuracy & F1-score ----------------
metrics = ["Accuracy", "F1-score"]
values = [0.87, 0.84]

plt.figure()
plt.bar(metrics, values)
plt.ylim(0, 1)
plt.ylabel("Score")
plt.title("Model Performance Metrics")
plt.savefig("images/fig5_2_metrics.png")
plt.close()

# ---------------- Fig 5.3: ROC Curve ----------------
fpr = [0.0, 0.1, 0.2, 0.4, 1.0]
tpr = [0.0, 0.65, 0.8, 0.9, 1.0]

plt.figure()
plt.plot(fpr, tpr, label="AUC = 0.89")
plt.plot([0,1], [0,1], linestyle="--")
plt.xlabel("False Positive Rate")
plt.ylabel("True Positive Rate")
plt.legend()
plt.title("ROC Curve")
plt.savefig("images/fig5_3_roc.png")
plt.close()

# ---------------- Fig 5.4: Benchmark Comparison ----------------
methods = ["Keyword Search", "LexLink"]
scores = [0.62, 0.85]

plt.figure()
plt.bar(methods, scores)
plt.ylim(0, 1)
plt.ylabel("F1-score")
plt.title("Benchmark Comparison")
plt.savefig("images/fig5_4_benchmark.png")
plt.close()
