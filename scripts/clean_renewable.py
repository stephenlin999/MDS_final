from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_DIR / "Renewable.csv"
OUTPUT_PATH = PROJECT_DIR / "Renewable_cleaned.csv"
SHORT_GAP_LIMIT = 8  # 15-minute data => up to 2 hours uses time interpolation.

CONTINUOUS_COLUMNS = [
    "Energy delta[Wh]",
    "GHI",
    "temp",
    "pressure",
    "humidity",
    "wind_speed",
    "rain_1h",
    "snow_1h",
    "clouds_all",
    "sunlightTime",
    "dayLength",
    "SunlightTime/daylength",
]


@dataclass
class CleaningReport:
    input_rows: int
    output_rows: int
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    base_frequency: str
    missing_timestamps_before_fill: int
    incomplete_hours_before_fill: int
    ghi_negative_clipped: int
    humidity_out_of_range_clipped: int
    wind_speed_negative_clipped: int
    night_ghi_zeroed: int
    isolated_daytime_ghi_spikes_replaced: int

    def as_text(self) -> str:
        return "\n".join(
            [
                f"Input rows: {self.input_rows}",
                f"Output rows: {self.output_rows}",
                f"Time range: {self.start_time} -> {self.end_time}",
                f"Inferred base frequency: {self.base_frequency}",
                f"Missing timestamps before fill: {self.missing_timestamps_before_fill}",
                f"Hours with incomplete 15-minute coverage before fill: {self.incomplete_hours_before_fill}",
                f"Negative GHI clipped to 0: {self.ghi_negative_clipped}",
                f"Humidity outside [0, 100] clipped: {self.humidity_out_of_range_clipped}",
                f"Negative wind speed clipped to 0: {self.wind_speed_negative_clipped}",
                f"Night-time GHI forced to 0: {self.night_ghi_zeroed}",
                f"Isolated daytime GHI spikes replaced and re-filled: {self.isolated_daytime_ghi_spikes_replaced}",
            ]
        )


def infer_base_frequency(index: pd.DatetimeIndex) -> pd.Timedelta:
    diffs = index.to_series().diff().dropna()
    if diffs.empty:
        raise ValueError("Need at least two timestamps to infer frequency.")
    return diffs.mode().iloc[0]


def fill_by_calendar_average(series: pd.Series, calendar_frame: pd.DataFrame) -> pd.Series:
    filled = series.interpolate(method="time", limit=SHORT_GAP_LIMIT, limit_direction="both")

    month_hour_minute_lookup = (
        pd.DataFrame(
            {
                "value": filled,
                "month": calendar_frame["month"],
                "hour": calendar_frame["hour"],
                "minute": calendar_frame["minute"],
            }
        )
        .dropna(subset=["value"])
        .groupby(["month", "hour", "minute"])["value"]
        .mean()
    )

    hour_minute_lookup = (
        pd.DataFrame(
            {
                "value": filled,
                "hour": calendar_frame["hour"],
                "minute": calendar_frame["minute"],
            }
        )
        .dropna(subset=["value"])
        .groupby(["hour", "minute"])["value"]
        .mean()
    )

    month_hour_minute_index = pd.MultiIndex.from_frame(calendar_frame[["month", "hour", "minute"]])
    hour_minute_index = pd.MultiIndex.from_frame(calendar_frame[["hour", "minute"]])

    month_hour_minute_fill = pd.Series(
        month_hour_minute_lookup.reindex(month_hour_minute_index).to_numpy(),
        index=filled.index,
    )
    hour_minute_fill = pd.Series(
        hour_minute_lookup.reindex(hour_minute_index).to_numpy(),
        index=filled.index,
    )

    filled = filled.fillna(month_hour_minute_fill)
    filled = filled.fillna(hour_minute_fill)
    filled = filled.interpolate(method="time", limit_direction="both")

    return filled


def fill_categorical_mode(series: pd.Series, calendar_frame: pd.DataFrame) -> pd.Series:
    observed = pd.DataFrame(
        {
            "value": series,
            "month": calendar_frame["month"],
            "hour": calendar_frame["hour"],
            "minute": calendar_frame["minute"],
        }
    ).dropna(subset=["value"])

    month_hour_minute_lookup = observed.groupby(["month", "hour", "minute"])["value"].agg(
        lambda x: x.mode().iloc[0]
    )

    hour_minute_lookup = observed.groupby(["hour", "minute"])["value"].agg(lambda x: x.mode().iloc[0])

    month_hour_minute_index = pd.MultiIndex.from_frame(calendar_frame[["month", "hour", "minute"]])
    hour_minute_index = pd.MultiIndex.from_frame(calendar_frame[["hour", "minute"]])

    month_hour_minute_fill = pd.Series(
        month_hour_minute_lookup.reindex(month_hour_minute_index).to_numpy(),
        index=series.index,
    )
    hour_minute_fill = pd.Series(
        hour_minute_lookup.reindex(hour_minute_index).to_numpy(),
        index=series.index,
    )

    filled = series.fillna(month_hour_minute_fill)
    filled = filled.fillna(hour_minute_fill)
    filled = filled.ffill().bfill()

    return filled


def clean_dataset(input_path: Path = INPUT_PATH, output_path: Path = OUTPUT_PATH) -> CleaningReport:
    df = pd.read_csv(input_path, parse_dates=["Time"]).sort_values("Time")
    input_rows = len(df)

    if df["Time"].duplicated().any():
        duplicate_count = int(df["Time"].duplicated().sum())
        raise ValueError(f"Found {duplicate_count} duplicate timestamps.")

    time_index = pd.DatetimeIndex(df["Time"])
    base_frequency = infer_base_frequency(time_index)
    full_index = pd.date_range(time_index.min(), time_index.max(), freq=base_frequency)
    missing_timestamps = full_index.difference(time_index)

    counts_per_hour = df["Time"].dt.floor("h").value_counts()
    full_hour_index = pd.date_range(time_index.min().floor("h"), time_index.max().floor("h"), freq="h")
    counts_per_hour = counts_per_hour.reindex(full_hour_index, fill_value=0)
    expected_points_per_hour = int(pd.Timedelta(hours=1) / base_frequency)
    incomplete_hours_before_fill = int((counts_per_hour < expected_points_per_hour).sum())

    df = df.set_index("Time").reindex(full_index)
    df.index.name = "Time"

    calendar_frame = pd.DataFrame(index=df.index)
    calendar_frame["month"] = df.index.month
    calendar_frame["hour"] = df.index.hour
    calendar_frame["minute"] = df.index.minute

    ghi_negative_clipped = int(df["GHI"].lt(0).sum(skipna=True))
    humidity_out_of_range_clipped = int((df["humidity"].lt(0) | df["humidity"].gt(100)).sum(skipna=True))
    wind_speed_negative_clipped = int(df["wind_speed"].lt(0).sum(skipna=True))

    df["GHI"] = df["GHI"].clip(lower=0)
    df["humidity"] = df["humidity"].clip(lower=0, upper=100)
    df["wind_speed"] = df["wind_speed"].clip(lower=0)
    df["clouds_all"] = df["clouds_all"].clip(lower=0, upper=100)
    df["rain_1h"] = df["rain_1h"].clip(lower=0)
    df["snow_1h"] = df["snow_1h"].clip(lower=0)

    night_ghi_mask = (df["GHI"] > 0) & ((df["isSun"] == 0) | (df["sunlightTime"].fillna(0) == 0))
    night_ghi_zeroed = int(night_ghi_mask.sum())
    df.loc[night_ghi_mask, "GHI"] = 0

    prev_ghi = df["GHI"].shift(1)
    next_ghi = df["GHI"].shift(-1)
    neighbor_max = pd.concat([prev_ghi, next_ghi], axis=1).max(axis=1)
    isolated_daytime_spike_mask = (
        df["GHI"].notna()
        & df["isSun"].eq(1)
        & prev_ghi.notna()
        & next_ghi.notna()
        & (neighbor_max <= 20)
        & (df["GHI"] >= 120)
        & (df["GHI"] >= (neighbor_max + 1) * 6)
    )
    isolated_daytime_ghi_spikes_replaced = int(isolated_daytime_spike_mask.sum())
    df.loc[isolated_daytime_spike_mask, "GHI"] = np.nan

    for column in CONTINUOUS_COLUMNS:
        df[column] = fill_by_calendar_average(df[column], calendar_frame)

    df["sunlightTime"] = df["sunlightTime"].clip(lower=0)
    df["dayLength"] = df["dayLength"].clip(lower=0)
    df["sunlightTime"] = np.minimum(df["sunlightTime"], df["dayLength"])
    df["SunlightTime/daylength"] = np.where(
        df["dayLength"] > 0,
        df["sunlightTime"] / df["dayLength"],
        0,
    )
    df["SunlightTime/daylength"] = df["SunlightTime/daylength"].clip(lower=0, upper=1)
    df["isSun"] = ((df["sunlightTime"] > 0) & (df["sunlightTime"] <= df["dayLength"])).astype(int)

    df["weather_type"] = fill_categorical_mode(df["weather_type"], calendar_frame)

    df["hour"] = calendar_frame["hour"]
    df["month"] = calendar_frame["month"]

    integer_columns = ["clouds_all", "isSun", "weather_type", "hour", "month"]
    for column in integer_columns:
        df[column] = df[column].round().astype(int)

    if df.isna().sum().sum():
        remaining = df.isna().sum()
        remaining = remaining[remaining > 0]
        raise ValueError(f"Cleaning left missing values behind:\n{remaining.to_string()}")

    output_rows = len(df)
    df.reset_index().to_csv(output_path, index=False)

    return CleaningReport(
        input_rows=input_rows,
        output_rows=output_rows,
        start_time=full_index.min(),
        end_time=full_index.max(),
        base_frequency=str(base_frequency),
        missing_timestamps_before_fill=len(missing_timestamps),
        incomplete_hours_before_fill=incomplete_hours_before_fill,
        ghi_negative_clipped=ghi_negative_clipped,
        humidity_out_of_range_clipped=humidity_out_of_range_clipped,
        wind_speed_negative_clipped=wind_speed_negative_clipped,
        night_ghi_zeroed=night_ghi_zeroed,
        isolated_daytime_ghi_spikes_replaced=isolated_daytime_ghi_spikes_replaced,
    )


def main() -> None:
    report = clean_dataset()
    print(report.as_text())
    print(f"\nCleaned file written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
