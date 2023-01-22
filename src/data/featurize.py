

# User stats feature engineering


def add_user_stats(interactions_df, users_df, split_name=""):
    """
    Computes user watches stats for particular interactions date split
    and adds them to users dataframe with specific name
    """
    user_watch_count_all = (
        interactions_df[interactions_df["total_dur"] > 300]
        .groupby(by="user_id")["item_id"]
        .count()
    )
    max_date_df = interactions_df["last_watch_dt"].max()
    user_watch_count_last_14 = (
        interactions_df[
            (interactions_df["total_dur"] > 300)
            & (
                interactions_df["last_watch_dt"]
                >= (max_date_df - pd.Timedelta(days=14))
            )
        ]
        .groupby(by="user_id")["item_id"]
        .count()
    )
    user_watch_count_all.name = split_name + "user_watch_cnt_all"
    user_watch_count_last_14.name = split_name + "user_watch_cnt_last_14"
    user_watches = pd.DataFrame(user_watch_count_all).join(
        user_watch_count_last_14, how="outer"
    )
    user_watches.fillna(0, inplace=True)
    cols = user_watches.columns
    user_watches[cols] = user_watches[cols].astype("int64")
    users_df = users_df.join(user_watches, on="user_id", how="outer")
    users_df[cols] = users_df[cols].fillna(0)
    users_df["age"] = users_df["age"].fillna("age_unknown")
    users_df["income"] = users_df["income"].fillna("income_unknown")
    users_df["sex"] = users_df["sex"].fillna("sex_unknown")
    users_df["kids_flg"] = users_df["kids_flg"].fillna(False)
    return users_df


max_date = interactions_df["last_watch_dt"].max()
boosting_split_date = max_date - pd.Timedelta(days=14)
interactions_boost = interactions_df[
    interactions_df["last_watch_dt"] <= boosting_split_date
]
users_df = add_user_stats(interactions_boost, users_df, split_name="boost_")
users_df = add_user_stats(interactions_df, users_df, split_name="")

# TODO: SAVE HERE!!

# Item stats feature engineering


def add_item_watches_stats(interactions_df, items_df, item_stats):
    """
    Computes item watches stats for particular interactions date split
    and adds them to item_stats dataframe
    """

    def smooth(series, window_size, smoothing_func):
        """Computes smoothed interactions statistics for item"""
        series = np.array(series)
        ext = np.r_[
            2 * series[0] - series[window_size - 1 :: -1],
            series,
            2 * series[-1] - series[-1:-window_size:-1],
        ]
        weights = smoothing_func(window_size)
        smoothed = np.convolve(weights / weights.sum(), ext, mode="same")
        return smoothed[window_size : -window_size + 1]

    def trend_slope(series, window_size=7, smoothing_func=np.hamming):
        """Computes trend slope for item interactions"""
        smoothed = smooth(series, window_size, smoothing_func)
        return smoothed[-1] - smoothed[-2]

    keep = item_stats.columns
    max_date = interactions_df["last_watch_dt"].max()
    cols = list(range(7))
    for col in cols:
        watches = interactions_df[
            interactions_df["last_watch_dt"] == max_date - pd.Timedelta(days=6 - col)
        ]
        item_stats = item_stats.join(
            watches.groupby("item_id")["user_id"].count(), lsuffix=col
        )
    item_stats.fillna(0, inplace=True)
    new_colnames = ["user_id" + str(i) for i in range(1, 7)] + ["user_id"]
    trend_slope_to_row = lambda row: trend_slope(row[new_colnames], window_size=7)
    item_stats["trend_slope"] = item_stats.apply(trend_slope_to_row, axis=1)
    item_stats["watched_in_7_days"] = item_stats[new_colnames].apply(sum, axis=1)
    item_stats["watch_ts_quantile_95"] = 0
    item_stats["watch_ts_median"] = 0
    item_stats["watch_ts_std"] = 0
    for item_id in item_stats.index:
        watches = interactions_df[interactions_df["item_id"] == item_id]
        day_of_year = (
            watches["last_watch_dt"].apply(lambda x: x.dayofyear).astype(np.int64)
        )
        item_stats.loc[item_id, "watch_ts_quantile_95"] = day_of_year.quantile(
            q=0.95, interpolation="nearest"
        )
        item_stats.loc[item_id, "watch_ts_median"] = day_of_year.quantile(
            q=0.5, interpolation="nearest"
        )
        item_stats.loc[item_id, "watch_ts_std"] = day_of_year.std()
    item_stats["watch_ts_quantile_95_diff"] = (
        max_date.dayofyear - item_stats["watch_ts_quantile_95"]
    )
    item_stats["watch_ts_median_diff"] = (
        max_date.dayofyear - item_stats["watch_ts_median"]
    )
    watched_all_time = interactions_df.groupby("item_id")["user_id"].count()
    watched_all_time.name = "watched_in_all_time"
    item_stats = item_stats.join(watched_all_time, on="item_id", how="left")
    item_stats.fillna(0, inplace=True)
    added_cols = [
        "trend_slope",
        "watched_in_7_days",
        "watch_ts_quantile_95_diff",
        "watch_ts_median_diff",
        "watch_ts_std",
        "watched_in_all_time",
    ]
    return item_stats[list(keep) + added_cols]


def add_age_stats(interactions, item_stats, users_df):
    """
    Computes watchers age stats for items with particular interactions
    date split and adds them to item_stats dataframe
    """
    item_stats.reset_index(inplace=True)
    interactions = interactions.set_index("user_id").join(
        users_df[["user_id", "sex", "age", "income"]].set_index("user_id")
    )
    interactions.reset_index(inplace=True)
    interactions["age_overall"] = interactions["age"].replace(
        to_replace={
            "age_18_24": "less_35",
            "age_25_34": "less_35",
            "age_35_44": "over_35",
            "age_45_54": "over_35",
            "age_65_inf": "over_35",
            "age_55_64": "over_35",
        }
    )
    age_stats = interactions.groupby("item_id")["age_overall"].value_counts(
        normalize=True
    )
    age_stats = pd.DataFrame(age_stats)
    age_stats.columns = ["value"]
    age_stats.reset_index(inplace=True)
    age_stats.columns = ["item_id", "age_overall", "value"]
    age_stats = age_stats.pivot(
        index="item_id", columns="age_overall", values="value"
    ).drop("age_unknown", axis=1)
    age_stats.fillna(0, inplace=True)
    item_stats = item_stats.set_index("item_id").join(age_stats)
    item_stats[["less_35", "over_35"]] = item_stats[["less_35", "over_35"]].fillna(0)
    item_stats.rename(
        columns={"less_35": "younger_35_fraction", "over_35": "older_35_fraction"},
        inplace=True,
    )
    return item_stats


def add_sex_stats(interactions, item_stats, users_df):
    """
    Computes watchers sex stats for items with particular interactions date split
    and adds them to item_stats dataframe
    """
    item_stats.reset_index(inplace=True)
    interactions = interactions.set_index("user_id").join(
        users_df[["user_id", "sex", "age", "income"]].set_index("user_id")
    )
    interactions.reset_index(inplace=True)
    sex_stats = interactions.groupby("item_id")["sex"].value_counts(normalize=True)
    sex_stats = pd.DataFrame(sex_stats)
    sex_stats.columns = ["value"]
    sex_stats.reset_index(inplace=True)
    sex_stats.columns = ["item_id", "sex", "value"]
    sex_stats = sex_stats.pivot(index="item_id", columns="sex", values="value").drop(
        "sex_unknown", axis=1
    )
    sex_stats.fillna(0, inplace=True)
    item_stats = item_stats.set_index("item_id").join(sex_stats)
    item_stats[["F", "M"]] = item_stats[["F", "M"]].fillna(0)
    item_stats.rename(
        columns={"F": "female_watchers_fraction", "M": "male_watchers_fraction"},
        inplace=True,
    )
    return item_stats


# Item stats for submit
item_stats = items_df[["item_id"]]
item_stats = item_stats.set_index("item_id")
item_stats = add_item_watches_stats(interactions_df, items_df, item_stats)
item_stats.fillna(0, inplace=True)
item_stats = add_sex_stats(interactions_df, item_stats, users_df)
item_stats = add_age_stats(interactions_df, item_stats, users_df)
item_stats.to_csv("data/item_stats_for_submit.csv", index=True)

# Item stats for boosting training
item_stats = items_df[["item_id"]]
item_stats = item_stats.set_index("item_id")
item_stats = add_item_watches_stats(interactions_boost, items_df, item_stats)
item_stats.fillna(0, inplace=True)
item_stats = add_sex_stats(interactions_boost, item_stats, users_df)
item_stats = add_age_stats(interactions_boost, item_stats, users_df)
item_stats.to_csv("data/item_stats_for_boost_train.csv", index=True)


