import argparse
import datetime
import logging
import re

import pandas as pd
import plotly.express as px
import streamlit as st

from collections import defaultdict
from copy import deepcopy

from opensearchpy import OpenSearch

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
                    {"term": {"program.keyword": "terraform"}},
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
                    {"term": {"program.keyword": "cloud-init"}},
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
        return OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_compress=True,
            http_auth=(username, password),
            use_ssl=True,
            url_prefix=url_prefix,
            headers=headers,
        )
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

    return pd.DataFrame(entries)


def search_puppet(es, index, run_id):
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"run_id.keyword": run_id}},
                    {"term": {"program.keyword": "puppet-agent"}},
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
                    },
                    "failure": {
                        "filter": {"match": {"message": "failed"}},
                        "aggs": {
                            "last_failure": {
                                "top_hits": {
                                    "size": 30,
                                    "sort": [{"@timestamp": "desc"}],
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
        hits = entry["first_applied_message"]["first_message"]["hits"]["hits"]
        if len(hits) == 0:
            continue

        source = hits[0]["_source"]
        message = source["message"]
        host = source["host"]
        match = re.search(PUPPET_DURATION_REGEX, message)
        if match:
            duration = float(match.group())
            delta = datetime.timedelta(seconds=duration)
            end = pd.to_datetime(source["@timestamp"])
            start = end - delta

        errors = 0
        if entry['failure']['doc_count'] > 0:
            hits = entry['failure']['last_failure']['hits']['hits']
            puppet_errors = defaultdict(list)
            for hit in hits:
                message = hit['_source']['message']
                if message.startswith('(/Stage[main]'):
                    key = message[message.find("(")+1:message.find(")")]
                    puppet_errors[key].append(message)
            unique_err = puppet_errors.keys()
            errors = len(unique_err)
            # if errors > 0:
                # print(host, unique_err)
                # import pdb; pdb.set_trace()

        entries.append({"host": host, "start": start, "end": end, "errors": errors})

    return pd.DataFrame(entries)

@st.cache_data(ttl="1h")
def get_run_ids(_es, index, limit=28):
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

    return [bucket["key"] for bucket in res["aggregations"]["unique_values"]["buckets"]]


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
    df["duration"] = df["end"] - df["start"]
    return df


def check_failure(df):
    result = []
    required_programs = set(["puppet", "cloudinit", "terraform"])

    def has_missing_programs(programs):
        return len(required_programs - set(programs)) > 0

    for run_id, group in df.groupby("run_id"):
        if (
            group['errors'].sum() > 0 or
            has_missing_programs(group["program"].tolist())
        ):
            result.append(run_id)
    return result

def draw_dashboard(df):
    if df is None:
        return

    workspaces = sorted(df['workspace'].unique())

    with st.sidebar:
        workspaces_options = st.multiselect(
            "Clouds",
            workspaces,
            default=workspaces,
            format_func=lambda x: x.title(),
        )
        df = df[df["workspace"].isin(workspaces_options)]
        if df.empty:
            st.warning("Select at least one cloud")
            return

        min_date = datetime.datetime(*df["start"].min().to_pydatetime().timetuple()[:3], tzinfo=datetime.timezone.utc)
        max_date = datetime.datetime(*df["end"].max().to_pydatetime().timetuple()[:3], tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)
        date_range = st.slider(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        df = df[(df["start"] >= date_range[0]) & (df["end"] <= date_range[1])]
        if df.empty:
            st.warning("No runs in selected date range")
            return

    failed_runs = check_failure(df)

    total_mask = df["program"] == "total"
    runs = df[total_mask].set_index('run_id')
    runs = runs.sort_values(["workspace", "start"])
    runs.reset_index()
    fig = px.bar(
        runs,
        x="start",
        y=runs["duration"] + pd.Timestamp("1970/01/01"),
        color="workspace",
        facet_col="workspace",
        labels={
            "workspace": "Cloud",
            "start": "Date",
            "y": "Duration",
        },
    )
    fig.update_layout(yaxis_tickformat="%H:%M:%S")
    fig.update_yaxes(hoverformat="%H:%M:%S")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1].title()))

    # Add a red "X" annotation on fail run
    map_facet = {x["name"]: f"x{i+1}" for i, x in enumerate(fig.data)}
    for run_id in failed_runs:
        run = runs.loc[run_id]
        workspace = run['workspace']
        xref = map_facet[workspace]
        fig.add_annotation(
            x=run['start'],
            xref=xref,
            y=pd.Timestamp("1970/01/01"),
            text="X",
            showarrow=False,
            font=dict(color="red"),
        )

    st.plotly_chart(fig)

    labels_to_run_id = {}
    for i, (run_id, run) in enumerate(runs.iterrows()):
        start_ = run['start'].strftime("%Y-%m-%d, %H:%M:%S UTC")
        duration = "{1:02}:{2:02}:{3:02}".format(*run['duration'].components)
        label = f"{i+1}: {run['workspace']} - {start_} ({duration})"
        labels_to_run_id[label] = run_id

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
                hover_data=["errors"],
            )

            fig.update_yaxes(autorange="reversed")
            fig.update_layout(title=label)
            st.plotly_chart(fig)

def main(load, save):
    st.header("MCSpeed Dashboard")

    username = st.secrets.get("opensearch_username")
    password = st.secrets.get("opensearch_password")
    host = st.secrets.get("opensearch_host")
    url_prefix = st.secrets.get("opensearch_url_prefix")
    headers = st.secrets.get("opensearch_headers")
    port = 443

    if load:
        try:
            df = pd.read_pickle('mcspeed.pickle')
        except:
            st.warning('Could not load data')
            df = None
        else:
            st.success("Loaded data from disk")
    else:
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

    if save:
        df.to_pickle('mcspeed.pickle')
    draw_dashboard(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='mcspeed')
    parser.add_argument('--load', action='store_true')  # on/off flag
    parser.add_argument('--save', action='store_true')  # on/off flag
    args = parser.parse_args()
    main(args.load, args.save)
