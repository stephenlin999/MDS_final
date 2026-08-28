# EMS Dashboard

Independent Streamlit dashboard for inspecting the EMS MILP outputs from:

```text
/Users/stephenlin/Downloads/mds-final/output
```

Install dashboard-only dependencies from this folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r /Users/stephenlin/Downloads/mds-final/requirements.txt
.venv/bin/streamlit run app.py
```

The app defaults to the existing `output/ems_2018` and baseline comparison files. Scenario reruns call the EMS engine through:

```bash
python3 /Users/stephenlin/Downloads/mds-final/ems_run.py
```

Scenario outputs are written under `dashboard/scenario_runs/` and are ignored by git.
