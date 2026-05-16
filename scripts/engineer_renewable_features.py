from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from clean_renewable import INPUT_PATH, OUTPUT_PATH as CLEANED_PATH, clean_dataset


PROJECT_DIR = Path(__file__).resolve().parents[1]
FEATURE_OUTPUT_PATH = PROJECT_DIR / "Renewable_featured.csv"
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
STEPS_PER_HOUR = 4
STEPS_PER_3_HOURS = 12
STEPS_PER_DAY = 96
PVLIB_TIMEZONE = "UTC"


@dataclass
class FeatureReport:
    input_rows: int
    output_rows: int
    estimated_latitude_deg: float
    estimated_longitude_deg: float
    added_feature_count: int
    rows_with_incomplete_history: int
    clear_sky_index_above_one_count: int

    def as_text(self) -> str:
        return "\n".join(
            [
                f"Input rows: {self.input_rows}",
                f"Output rows: {self.output_rows}",
                f"Estimated latitude from day length: {self.estimated_latitude_deg:.2f} deg",
                f"Estimated longitude from solar noon: {self.estimated_longitude_deg:.2f} deg",
                f"Added feature columns: {self.added_feature_count}",
                f"Rows with incomplete lag/rolling history: {self.rows_with_incomplete_history}",
                f"Rows where clear sky index > 1: {self.clear_sky_index_above_one_count}",
                f"Featured file written to: {FEATURE_OUTPUT_PATH}",
            ]
        )


def solar_declination_rad(day_of_year: np.ndarray) -> np.ndarray:
    gamma = 2 * np.pi * (day_of_year - 1) / 365.0
    return (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )


def expected_daylength_minutes(latitude_deg: float, day_of_year: np.ndarray) -> np.ndarray:
    latitude_rad = np.deg2rad(latitude_deg)
    declination = solar_declination_rad(day_of_year)
    sunset_hour_angle = np.arccos(np.clip(-np.tan(latitude_rad) * np.tan(declination), -1, 1))
    return (2 * np.rad2deg(sunset_hour_angle) / 15.0) * 60.0


def estimate_latitude_from_daylength(input_path: Path = INPUT_PATH) -> float:
    raw = pd.read_csv(input_path, parse_dates=["Time"])
    daily = raw.groupby(raw["Time"].dt.floor("D")).agg(dayLength=("dayLength", "median"))
    day_of_year = daily.index.dayofyear.to_numpy()
    observed = daily["dayLength"].to_numpy()

    coarse_grid = np.arange(-66.0, 66.0001, 0.25)
    coarse_loss = [
        np.mean(np.abs(expected_daylength_minutes(latitude, day_of_year) - observed))
        for latitude in coarse_grid
    ]
    coarse_best = float(coarse_grid[int(np.argmin(coarse_loss))])

    fine_grid = np.arange(coarse_best - 1.0, coarse_best + 1.0001, 0.01)
    fine_loss = [
        np.mean(np.abs(expected_daylength_minutes(latitude, day_of_year) - observed))
        for latitude in fine_grid
    ]
    return float(fine_grid[int(np.argmin(fine_loss))])


def equation_of_time_minutes(day_of_year: np.ndarray) -> np.ndarray:
    angle = 2 * np.pi * (day_of_year - 81) / 364.0
    return 9.87 * np.sin(2 * angle) - 7.53 * np.cos(angle) - 1.5 * np.sin(angle)


def estimate_longitude_from_solar_noon(input_path: Path = INPUT_PATH) -> float:
    raw = pd.read_csv(input_path, parse_dates=["Time"])
    daylight = raw[(raw["isSun"] == 1) & (raw["dayLength"] > 0)].copy()
    daylight["solar_noon_candidate"] = (
        daylight["Time"]
        - pd.to_timedelta(daylight["sunlightTime"], unit="m")
        + pd.to_timedelta(daylight["dayLength"] / 2.0, unit="m")
    )

    daily_noon = daylight.groupby(daylight["Time"].dt.floor("D"))["solar_noon_candidate"].median()
    solar_noon_minutes = daily_noon.dt.hour * 60 + daily_noon.dt.minute + daily_noon.dt.second / 60
    day_of_year = daily_noon.index.dayofyear.to_numpy()
    longitude = (720.0 - equation_of_time_minutes(day_of_year) - solar_noon_minutes.to_numpy()) / 4.0

    return float(np.nanmedian(longitude))


def load_pvlib_modules():
    if LOCAL_PACKAGE_DIR.exists():
        sys.path.insert(0, str(LOCAL_PACKAGE_DIR))

    from pvlib import irradiance
    from pvlib.location import Location

    return Location, irradiance


def localize_for_pvlib(timestamp: pd.Series) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(timestamp).tz_localize(PVLIB_TIMEZONE)


def add_astronomy_features(
    df: pd.DataFrame,
    latitude_deg: float,
    longitude_deg: float,
) -> pd.DataFrame:
    Location, irradiance = load_pvlib_modules()

    result = df.copy()
    pvlib_times = localize_for_pvlib(result["Time"])
    location = Location(
        latitude=latitude_deg,
        longitude=longitude_deg,
        tz=PVLIB_TIMEZONE,
        altitude=0,
        name="estimated_site",
    )

    solar_position = location.get_solarposition(
        pvlib_times,
        pressure=result["pressure"].to_numpy() * 100.0,
        temperature=result["temp"].to_numpy(),
    )
    clear_sky = location.get_clearsky(
        pvlib_times,
        model="ineichen",
        solar_position=solar_position,
    )

    solar_elevation_deg = solar_position["apparent_elevation"].to_numpy()
    solar_zenith_deg = solar_position["apparent_zenith"].to_numpy()
    cos_zenith = np.clip(np.cos(np.deg2rad(solar_zenith_deg)), 0, None)
    ghi_clear_sky_wm2 = clear_sky["ghi"].clip(lower=0).to_numpy()
    dni_clear_sky_wm2 = clear_sky["dni"].clip(lower=0).to_numpy()
    dhi_clear_sky_wm2 = clear_sky["dhi"].clip(lower=0).to_numpy()
    dni_extra = irradiance.get_extra_radiation(pvlib_times).to_numpy()
    ghi_toa_horizontal_wm2 = np.clip(dni_extra * cos_zenith, 0, None)

    clear_sky_index = np.divide(
        result["GHI"].to_numpy(),
        ghi_clear_sky_wm2,
        out=np.zeros_like(ghi_clear_sky_wm2),
        where=ghi_clear_sky_wm2 > 1.0,
    )
    clear_sky_index = np.clip(clear_sky_index, 0, 1.5)
    cloud_cover_proxy = np.clip(1.0 - clear_sky_index, 0, 1)
    day_of_year = result["Time"].dt.dayofyear.to_numpy()

    result["site_latitude_deg"] = latitude_deg
    result["site_longitude_deg"] = longitude_deg
    result["solar_declination_deg"] = np.rad2deg(solar_declination_rad(day_of_year))
    result["solar_hour_angle_deg"] = (result["Time"].dt.hour + result["Time"].dt.minute / 60.0 - 12.0) * 15.0
    result["solar_elevation_deg"] = solar_elevation_deg
    result["solar_zenith_deg"] = solar_zenith_deg
    result["solar_azimuth_deg"] = solar_position["azimuth"].to_numpy()
    result["cos_solar_zenith"] = cos_zenith
    result["ghi_toa_horizontal_wm2"] = ghi_toa_horizontal_wm2
    result["ghi_clear_sky_wm2"] = ghi_clear_sky_wm2
    result["dni_clear_sky_wm2"] = dni_clear_sky_wm2
    result["dhi_clear_sky_wm2"] = dhi_clear_sky_wm2
    result["clear_sky_index"] = clear_sky_index
    result["cloud_cover_proxy"] = cloud_cover_proxy

    return result


def add_lag_and_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    lag_columns = {
        "GHI": "ghi",
        "clear_sky_index": "clear_sky_index",
        "Energy delta[Wh]": "energy_delta",
    }

    for source_column, prefix in lag_columns.items():
        result[f"{prefix}_lag_1h"] = result[source_column].shift(STEPS_PER_HOUR)
        result[f"{prefix}_lag_3h"] = result[source_column].shift(STEPS_PER_3_HOURS)
        result[f"{prefix}_lag_1d"] = result[source_column].shift(STEPS_PER_DAY)

    # Shift by one step so rolling windows only use data strictly before time t.
    ghi_history = result["GHI"].shift(1)
    energy_history = result["Energy delta[Wh]"].shift(1)

    result["ghi_roll_mean_3h"] = ghi_history.rolling(
        STEPS_PER_3_HOURS,
        min_periods=STEPS_PER_3_HOURS,
    ).mean()
    result["ghi_roll_std_3h"] = ghi_history.rolling(
        STEPS_PER_3_HOURS,
        min_periods=STEPS_PER_3_HOURS,
    ).std()
    result["energy_roll_mean_3h"] = energy_history.rolling(
        STEPS_PER_3_HOURS,
        min_periods=STEPS_PER_3_HOURS,
    ).mean()

    return result


def add_time_encoding_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    timestamp = result["Time"]
    weekday = timestamp.dt.weekday
    month = timestamp.dt.month
    hour_fraction = timestamp.dt.hour + timestamp.dt.minute / 60.0

    result["weekday"] = weekday
    result["season"] = month.map(
        {
            12: 0,
            1: 0,
            2: 0,
            3: 1,
            4: 1,
            5: 1,
            6: 2,
            7: 2,
            8: 2,
            9: 3,
            10: 3,
            11: 3,
        }
    ).astype(int)
    result["is_weekend"] = weekday.isin([5, 6]).astype(int)

    result["hour_sin"] = np.sin(2 * np.pi * hour_fraction / 24.0)
    result["hour_cos"] = np.cos(2 * np.pi * hour_fraction / 24.0)
    result["weekday_sin"] = np.sin(2 * np.pi * weekday / 7.0)
    result["weekday_cos"] = np.cos(2 * np.pi * weekday / 7.0)
    result["month_sin"] = np.sin(2 * np.pi * (month - 1) / 12.0)
    result["month_cos"] = np.cos(2 * np.pi * (month - 1) / 12.0)

    return result


def add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["temp_x_ghi"] = result["temp"] * result["GHI"]
    result["humidity_x_cloud_cover"] = result["humidity"] * result["cloud_cover_proxy"]
    result["wind_x_clear_sky_index"] = result["wind_speed"] * result["clear_sky_index"]
    return result


def build_feature_dataset(
    cleaned_path: Path = CLEANED_PATH,
    feature_output_path: Path = FEATURE_OUTPUT_PATH,
) -> FeatureReport:
    if not cleaned_path.exists():
        clean_dataset()

    df = pd.read_csv(cleaned_path, parse_dates=["Time"]).sort_values("Time")
    input_rows = len(df)
    base_columns = set(df.columns)

    latitude_deg = estimate_latitude_from_daylength()
    longitude_deg = estimate_longitude_from_solar_noon()
    featured = add_astronomy_features(df, latitude_deg, longitude_deg)
    featured = add_lag_and_rolling_features(featured)
    featured = add_time_encoding_features(featured)
    featured = add_interaction_features(featured)

    added_feature_count = len(set(featured.columns) - base_columns)
    history_columns = [
        column
        for column in featured.columns
        if "_lag_" in column or "_roll_" in column
    ]
    rows_with_incomplete_history = int(featured[history_columns].isna().any(axis=1).sum())
    clear_sky_index_above_one_count = int((featured["clear_sky_index"] > 1.0).sum())

    featured = featured.drop(columns=["date", "solar_noon_time"], errors="ignore")
    featured.to_csv(feature_output_path, index=False)

    return FeatureReport(
        input_rows=input_rows,
        output_rows=len(featured),
        estimated_latitude_deg=latitude_deg,
        estimated_longitude_deg=longitude_deg,
        added_feature_count=added_feature_count,
        rows_with_incomplete_history=rows_with_incomplete_history,
        clear_sky_index_above_one_count=clear_sky_index_above_one_count,
    )


def main() -> None:
    report = build_feature_dataset()
    print(report.as_text())


if __name__ == "__main__":
    main()
