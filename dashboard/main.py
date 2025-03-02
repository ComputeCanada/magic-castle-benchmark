import streamlit as st
from opensearchpy import OpenSearch
from requests.auth import HTTPBasicAuth
import pandas as pd
import datetime
import re
import plotly.express as px
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INDEX = st.secrets.get("opensearch_index")
MAX_HOST_NB = 20

PUPPET_DURATION_REGEX = r"\d+(\.\d+)?"

pd.options.mode.copy_on_write = True


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


def get_workspace_from_run_id(es, index, run_id):
    try:
        body = {
            "size": 0,
            "query": {"term": {"run_id": run_id}},
            "aggs": {
                "unique_workspaces": {"terms": {"field": "workspace.keyword", "size": 10}}
            },
        }

        res = es.search(index=f"{index}", body=body)
        buckets = res["aggregations"]["unique_workspaces"]["buckets"]
        if len(buckets) != 1:
            raise Exception("Unknown workspace")
        else:
            return buckets[0]["key"]

    except Exception as e:
        logger.error(f"Error searching workspace for {run_id=}: {e}")
        st.error(f"Error searching workspace for {run_id=}. Please try again.")
        return pd.DataFrame()


def search_start_end(es, index, run_id, program):
    try:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"match": {"run_id": run_id}},
                        {"match": {"program": program}},
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
                "missing_host": {  # In Terraform case, there is no host
                    "missing": {"field": "host.keyword"},
                    "aggs": {
                        "max_timestamp": {"max": {"field": "@timestamp"}},
                        "min_timestamp": {"min": {"field": "@timestamp"}},
                    },
                },
            },
        }
        res = es.search(index=f"{index}", body=body)
        entries = []

        aggregations = res["aggregations"]
        missing_host = aggregations["missing_host"]
        if missing_host["doc_count"] != 0:
            # In Terraform case, there is no host
            start = pd.to_datetime(missing_host["min_timestamp"]["value_as_string"])
            end = pd.to_datetime(missing_host["max_timestamp"]["value_as_string"])
            host = None
            entries.append({"host": host, "start": start, "end": end})

        for entry in aggregations["hosts"]["buckets"]:
            start = pd.to_datetime(entry["min_timestamp"]["value_as_string"])
            end = pd.to_datetime(entry["max_timestamp"]["value_as_string"])
            host = entry["key"]
            entries.append({"host": host, "start": start, "end": end})

        df = pd.DataFrame(entries)
        return df

    except Exception as e:
        logger.error(f"Error searching {program} logs: {e}")
        return pd.DataFrame()


def search_puppet(es, index, run_id):
    try:
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must": [
                        {"match": {"run_id": run_id}},
                        {"match": {"program": "puppet-agent"}},
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

        res = es.search(index=f"{index}", body=body)
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
                entries.append({"host": host, "start": start, "end": end})

        df = pd.DataFrame(entries)
        return df
    except Exception as e:
        logger.error(f"Error searching puppet logs: {e}")
        return pd.DataFrame()


@st.cache_data(ttl="1h")
def get_run_ids(_es, index, limit=10):
    try:
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
        res = _es.search(index=index, body=query)
        unique_values = [
            bucket["key"] for bucket in res["aggregations"]["unique_values"]["buckets"]
        ]
        return unique_values
    except Exception as e:
        logger.error(f"Error listing unique values: {e}")
        return []

@st.cache_data(ttl="1d")
def get_single_run(_es, index, run_id):
    terraform_df = search_start_end(_es, f"{index}", run_id, "terraform")
    terraform_df["program"] = "terraform"
    terraform_df["host"] = "terraform"
    cloudinit_df = search_start_end(_es, f"{index}", run_id, "cloud-init")
    cloudinit_df["program"] = "cloudinit"
    puppet_df = search_puppet(_es, INDEX, run_id)
    puppet_df["program"] = "puppet"

    workspace = get_workspace_from_run_id(_es, index, run_id)

    df = pd.concat([terraform_df, puppet_df, cloudinit_df], ignore_index=True)
    df["run_id"] = run_id
    df["workspace"] = workspace
    return df

def get_all_run(es, index, run_ids):
    dfs = [get_single_run(es, index, run_id) for run_id in run_ids]
    df = pd.concat(dfs)

    total_program = (
        df.groupby(["run_id", "workspace"])
        .agg({"start": "min", "end": "max"})
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

    def has_required_programs(programs):
        return required_programs - set(programs)

    # Update duration_s and start based on missing programs
    for _, group in df.groupby("run_id"):
        programs = group["program"].tolist()
        missing_programs = has_required_programs(programs)
        if missing_programs:
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
        df = get_all_run(es, INDEX, run_ids)

        workspaces = df['workspace'].unique()

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
        failed_runs = check_failure(result)

        fig = px.bar(
            result[total_mask],
            x="start",
            y="duration_s",
            color="workspace",
            facet_col="workspace",
            labels={
                "start": "Date",
                "duration_s": "Deployment duration (s)",
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

        runs = df.groupby(["run_id", "workspace"])["start"].min().reset_index()
        runs = runs.sort_values(["workspace", "start"])
        labels_to_run_id = {}
        for _, run in runs.iterrows():
            label = f"{run['workspace']} - {run['start']}"
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
