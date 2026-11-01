# Bloom prediction models

Trains and compares a **Decision Tree**, a **Support Vector Machine (RBF kernel)** and a **Random Forest** that predict bloom / no bloom from the five probe readings: temperature, pH, turbidity, ORP and EC. Each model is scored on Accuracy, Precision, Recall and F1-Score. The model with the best F1 goes to the web app, which shows its live prediction on the Overview page. The full comparison is on the Model page.

## 1. Collect readings

Firmware v5 appends one reading per minute to `/readings` in the Realtime Database. Readings from an uncalibrated probe are logged, but training skips them. Each row also carries salinity in ppt, calculated from EC and temperature. Dissolved oxygen and ammonia columns stay empty until those probes are fitted.

```
pip install -r ml/requirements.txt
python ml/export_readings.py          # writes ml/data/readings.csv
```

## 2. Label them with field observations

The models learn from readings taken while you **know** whether a bloom was present. Copy `ml/observations.example.csv` to `ml/data/observations.csv` and add one row per field check:

| column | meaning |
|---|---|
| `start`, `end` | Philippine time window the label covers, `YYYY-MM-DD HH:MM` |
| `label` | `bloom` or `no_bloom` |
| `source` | visual check, BFAR shellfish bulletin, chlorophyll test kit, lab result |
| `notes` | anything useful |

Record the `no_bloom` checks as well as the blooms. The models need both classes, at least 10 readings of each. To evaluate fairly they also need each class seen on 2 or more different days.

Do not label readings with the alert thresholds. The models would only learn the thresholds back and score near 100%, which says nothing about real blooms.

## 3. Train

```
python ml/train.py --readings ml/data/readings.csv --observations ml/data/observations.csv
```

Outputs:

- `app/ml_models/metrics.json`: comparison table and confusion matrices, shown on the Model page
- `app/ml_models/bloom_model.json`: the best model, used for live predictions
- `ml/reports/metrics.csv`: the same table, for the paper
- `ml/reports/confusion_*.png`, `ml/reports/model_comparison.png`: figures

Commit `app/ml_models/` and redeploy so the website uses the new model.

### How the evaluation works

- **Test split by day.** Whole days are held out for testing (StratifiedGroupKFold). Readings a minute apart are nearly identical, so a random split would leak near-copies of test rows into training and inflate the scores. If there are too few labeled days, the script falls back to a random split and says so.
- **Hyperparameter tuning.** Uses 5-fold cross-validation on the training days only, choosing the settings with the best F1.
- **Class balance.** `class_weight="balanced"` stops the models from ignoring the rarer bloom class.
- **Best model.** Picked by test-set F1, because a missed bloom (false negative) and a false alarm both matter.

### No local dataset yet

Until the station has field labels, train on the public EPA Charles River buoy. That record has temperature, pH, turbidity and estimated chlorophyll-a. It has no ORP, and its conductivity is river water, so those two probes are left out. A 6-hour block is labeled `bloom` when estimated chlorophyll-a reaches 50 µg/L (WHO recreational Alert Level 2 for cyanobacteria). The lower 10 µg/L alert is a normal hour on this river, so it is not used. The Model page marks this model as a public stand-in. Do not report its scores as this station's results.

```
pip install -r ml/requirements.txt
python ml/prepare_public_dataset.py
python ml/train.py --dataset ml/data/public_bloom.csv --features temperature,ph,turbidity
```

AquaSense is a separate hourly pond file (`DO`, `pH`, `Temperature_C`, `NH3`, `Turbidity_NTU`, `Salinity_ppt`) with an `incident_type` column. Bloom is `algal_bloom_crash`. Salinity there is about 0.4 ppt, so it is not used as coastal EC, and there is no ORP. Pond-days are held out as groups so one pond's afternoon is not scored against its own morning.

```
python ml/prepare_aquasense.py
python ml/train.py --dataset ml/data/aquasense_bloom.csv --features temperature,ph,turbidity
```

Do not merge this file with the river dataset. The bloom labels are defined differently.

### Other data sources

Any CSV with the feature columns and a `label` column also works, for example a published labeled water-quality dataset:

```
python ml/train.py --dataset path/to/labeled.csv --features temperature,ph,turbidity
```

The web app then predicts from those features only. A first line of `# proxy: ...` marks the file as a stand-in dataset.

### Pipeline test

```
python ml/train.py --readings ml/data/readings.csv --demo
```

This labels readings with the firmware's alert thresholds, only to check that everything runs end to end. The Model page marks a demo model as such. Never report its scores.
