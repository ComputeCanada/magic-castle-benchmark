import streamlit as st
from opensearchpy import OpenSearch
import pandas as pd
import datetime
import re
import plotly.express as px
import logging
from copy import deepcopy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("opensearch").setLevel(logging.ERROR)

INDEX = st.secrets.get("opensearch_index")
MAX_HOST_NB = 20

PUPPET_DURATION_REGEX = r"\d+(\.\d+)?"

pd.options.mode.copy_on_write = True

START_END_QUERIES = {
    "terraform": {
        "size": 0,
        "query": {
            "bool": {
                "must": [
                    {"match": {"program": "terraform"}},
                    {"range": {"@timestamp": {"gte": "now/y", "lt": "now+1y/y"}}},
                ]
            }
        },
        "aggs": {
            "max_timestamp": {"max": {"field": "@timestamp"}},
            "min_timestamp": {"min": {"field": "@timestamp"}},
            "log_level": {
                "terms": {"field": "@level.keyword", "size": 5},
            }
        },
    },
    "cloud-init": {
        "size": 0,
        "query": {
            "bool": {
                "must": [
                    {"match": {"program": "cloud-init"}},
                    {"range": {"@timestamp": {"gte": "now/y", "lt": "now+1y/y"}}},
                ]
            }
        },
        "aggs": {
            "hosts": {
                "terms": {"field": "host.keyword", "size": MAX_HOST_NB},
                "aggs": {
                    "max_timestamp": {"max": {"field": "@timestamp"}},
                    "min_timestamp": {"min": {"field": "@timestamp"}},
                },
            },
        },
    },
}

def connect_to_opensearch(username, password, host, port, url_prefix=None, headers={}):
    try:
        es = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_compress=True,
            http_auth=(username, password),
            use_ssl=True,
            url_prefix=url_prefix,
            headers=headers,
        )
        return es
    except Exception as e:
        logger.error(f"Error connecting to OpenSearch: {e}")
        st.error(
            "Error connecting to OpenSearch. Please check your credentials and try again."
        )
        return None

def search_start_end(es, index, run_id, program):
    body = deepcopy(START_END_QUERIES[program])
    body["query"]["bool"]["must"].append({"match" : {"run_id" :  run_id}})

    try:
        res = es.search(index=f"{index}", body=body, request_timeout=30)
    except Exception as e:
        logger.error(f"Error searching {program} logs: {e}")
        return pd.DataFrame()
    logger.info(f"Search {program} start-end for {run_id} - {res['took'] / 1000.0}s")

    entries = []
    aggregations = res["aggregations"]
    if "hosts" in aggregations:
        for entry in aggregations["hosts"]["buckets"]:
            start = pd.to_datetime(entry["min_timestamp"]["value_as_string"])
            end = pd.to_datetime(entry["max_timestamp"]["value_as_string"])
            host = entry["key"]
            entries.append({"host": host, "start": start, "end": end, "errors": 0})
    elif "min_timestamp" in aggregations:
        try:
            start = pd.to_datetime(aggregations["min_timestamp"]["value_as_string"])
            end = pd.to_datetime(aggregations["max_timestamp"]["value_as_string"])
            errors = sum(bucket['doc_count'] for bucket in aggregations["log_level"]["buckets"] if bucket['key'] == 'error')
            entries.append({"host": None, "start": start, "end": end, "errors": errors})
        except:
            return pd.DataFrame()
    df = pd.DataFrame(entries)
    return df


def search_puppet(es, index, run_id):
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"match": {"run_id": run_id}},
                    {"match": {"program": "puppet-agent"}},
                    {"range": {"@timestamp": {"gte": "now/y", "lt": "now+1y/y"}}},
                ]
            }
        },
        "aggs": {
            "hosts": {
                "terms": {"field": "host.keyword", "size": 10},
                "aggs": {
                    "first_applied_message": {
                        "filter": {"match": {"message": "Applied"}},
                        "aggs": {
                            "first_message": {
                                "top_hits": {
                                    "size": 1,
                                    "sort": [{"@timestamp": "asc"}],
                                }
                            }
                        },
                    }
                },
            }
        },
    }
    try:
        res = es.search(index=f"{index}", body=body, request_timeout=30)
    except Exception as e:
        logger.error(f"Error searching puppet logs: {e}")
        return pd.DataFrame()
    logger.info(f"Search puppet start-end for {run_id} - {res['took'] / 1000.0}s")
    entries = []
    for entry in res["aggregations"]["hosts"]["buckets"]:
        source = entry["first_applied_message"]["first_message"]["hits"]["hits"][0][
            "_source"
        ]
        message = source["message"]
        host = source["host"]
        match = re.search(PUPPET_DURATION_REGEX, message)
        if match:
            duration = float(match.group())
            delta = datetime.timedelta(seconds=duration)
            end = pd.to_datetime(source["@timestamp"])
            start = end - delta
            entries.append({"host": host, "start": start, "end": end, "errors": 0})

    df = pd.DataFrame(entries)
    return df

@st.cache_data(ttl="1h")
def get_run_ids(_es, index, limit=10):
    query = {
        "size": 0,
        "aggs": {
            "unique_values": {
                "terms": {
                    "field": "run_id.keyword",
                    "size": limit,
                    "order": {
                        "first_event_occur": "desc"
                    }
                },
                "aggs": {
                    "first_event_occur": {
                        "min": {
                            "field": "@timestamp"
                        }
                    }
                }
            }
        }
    }

    try:
        res = _es.search(index=index, body=query, request_timeout=30)
    except Exception as e:
        logger.error(f"Error listing unique values: {e}")
        return []
    logger.info(f"Search last {limit} run ids - {res['took'] / 1000.0}s")
    unique_values = [
        bucket["key"] for bucket in res["aggregations"]["unique_values"]["buckets"]
    ]
    return unique_values


@st.cache_data(ttl="1d")
def get_single_run(_es, index, run_id):
    terraform_df = search_start_end(_es, f"{index}", run_id, "terraform")
    terraform_df["program"] = "terraform"
    terraform_df["host"] = "terraform"
    cloudinit_df = search_start_end(_es, f"{index}", run_id, "cloud-init")
    cloudinit_df["program"] = "cloudinit"
    puppet_df = search_puppet(_es, INDEX, run_id)
    puppet_df["program"] = "puppet"

    # run_id = github.run_id + "_" + workspace
    workspace = run_id.split("_")[-1]

    df = pd.concat([terraform_df, puppet_df, cloudinit_df], ignore_index=True)
    df["run_id"] = run_id
    df["workspace"] = workspace
    return df

def get_all_run(es, index, run_ids):
    dfs = [get_single_run(es, index, run_id) for run_id in run_ids]
    df = pd.concat(dfs)

    total_program = (
        df.groupby(["run_id", "workspace"])
        .agg({"start": "min", "end": "max", "errors": "sum"})
        .reset_index()
    )
    total_program["host"] = "total"
    total_program["program"] = "total"

    df = pd.concat([df, total_program])
    df["duration_s"] = (df["end"] - df["start"]).dt.total_seconds()
    return df


def check_failure(df):
    result = []
    required_programs = set(["puppet", "cloudinit", "terraform"])

    def has_missing_programs(programs):
        return len(required_programs - set(programs)) > 0

    # Update duration_s and start based on missing programs
    for _, group in df.groupby("run_id"):
        if (
            group['errors'].sum() > 0 or
            has_missing_programs(group["program"].tolist())
        ):
            start = group.iloc[0]["start"]
            workspace = group["workspace"].unique()[0]
            result.append((workspace, start))
    return result


def main():
    st.header("MCSpeed Dashboard")

    username = st.secrets.get("opensearch_username")
    password = st.secrets.get("opensearch_password")
    host = st.secrets.get("opensearch_host")
    url_prefix = st.secrets.get("opensearch_url_prefix")
    headers = st.secrets.get("opensearch_headers")
    port = 443

    es = st.session_state.get("es")
    if es is None:
        es = connect_to_opensearch(
            username, password, host, port, url_prefix=url_prefix, headers=headers
        )
        st.success("Connected to OpenSearch")
        st.session_state["es"] = es

    if es:
        run_ids = get_run_ids(es, INDEX)
        if len(run_ids) == 0:
            st.warning("No benchmark run found")
            get_run_ids.clear()
            return

        df = get_all_run(es, INDEX, run_ids)
        workspaces = df['workspace'].unique()
        failed_runs = check_failure(df)

        with st.sidebar:
            workspaces_options = st.multiselect(
                "Clouds",
                workspaces,
                default=workspaces,
                format_func=lambda x: x.title(),
            )
            df = df[df["workspace"].isin(workspaces_options)]

            min_date = df["start"].min().to_pydatetime()
            max_date = df["end"].max().to_pydatetime()
            date_range = st.slider(
                "Date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
            df = df[(df["start"] >= date_range[0]) & (df["end"] <= date_range[1])]

        program_duration = (
            df.groupby(["run_id", "program", "workspace"])["duration_s"]
            .max()
            .reset_index()
        )
        run_start = df.groupby(["run_id", "workspace"])["start"].min().reset_index()
        result = pd.merge(program_duration, run_start, on=["run_id", "workspace"])

        total_mask = result["program"] == "total"
        fig = px.bar(
            result[total_mask],
            x="start",
            y="duration_s",
            color="workspace",
            facet_col="workspace",
            labels={
                "start": "Date",
                "duration_s": "Duration (s)",
                "program": "Program",
            },
            hover_data=["run_id"],
        )
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1].title()))

        # Add a red "X" annotation on fail run
        map_facet = {x["name"]: f"x{i+1}" for i, x in enumerate(fig.data)}
        for workspace, start in failed_runs:
            xref = map_facet[workspace]
            fig.add_annotation(
                x=start,
                xref=xref,
                y=0,
                text="X",
                showarrow=False,
                font=dict(color="red"),
            )

        st.plotly_chart(fig)

        runs = df[df['host'] == 'total'].reset_index()
        runs = runs.sort_values(["workspace", "start"])
        labels_to_run_id = {}
        for _, run in runs.iterrows():
            start_ = run['start'].strftime("%Y-%m-%d, %H:%M:%S UTC")
            label = f"{run['workspace']} - {start_} ({run['duration_s']}s)"
            labels_to_run_id[label] = run["run_id"]
        labels = st.multiselect(
            "Runs", labels_to_run_id.keys(), format_func=lambda x: f"{x}", default=None
        )
        for label in labels:
            run_id = labels_to_run_id[label]
            df_single = df[df["run_id"] == run_id]

            if not df_single.empty:
                fig = px.timeline(
                    df_single,
                    x_start="start",
                    x_end="end",
                    y="host",
                    color="program",
                    category_orders={
                        "program": ["total", "terraform", "cloudinit", "puppet"]
                    },
                    hover_data=["duration_s"],
                )

                fig.update_yaxes(autorange="reversed")
                fig.update_layout(title=label)
                st.plotly_chart(fig)


if __name__ == "__main__":
    main()
