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

INDEX = "mcspeed"
MAX_HOST_NB = 20

PUPPET_DURATION_REGEX = r'\d+(\.\d+)?'

def connect_to_opensearch(username, password, host, port):
    try:
        es = OpenSearch(
            hosts=[{'host': host, 'port': port}],
            http_compress=True,
            http_auth=(username, password),
            use_ssl=True,
        )
        return es
    except Exception as e:
        logger.error(f"Error connecting to OpenSearch: {e}")
        st.error("Error connecting to OpenSearch. Please check your credentials and try again.")
        return None

def get_workspace_from_run_id(es, index, run_id):
    try:
        body = {
          "size": 0,
          "query": {
            "term": {
              "run_id": run_id
            }
          },
          "aggs": {
            "unique_workspaces": {
              "terms": {
                "field": "workspace",
                "size": 10
              }
            }
          }
        }

        res = es.search(index=f"{index}", body=body)
        buckets = res['aggregations']['unique_workspaces']['buckets']
        if len(buckets) != 1:
            raise Exception("Unknown workspace")
        else:
            return buckets[0]['key']

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
                {"match": {"program": program}}
              ]
            }
          },
          "aggs": {
            "hosts": {
              "terms": {
                "field": "host",
                "size": MAX_HOST_NB
              },
              "aggs": {
                "max_timestamp": {
                  "max": {
                    "field": "@timestamp"
                  }
                },
                "min_timestamp": {
                  "min": {
                    "field": "@timestamp"
                  }
                }
              }
            },
            "missing_host": {
              "missing": {
                "field": "host"
              },
              "aggs": {
                "max_timestamp": {
                  "max": {
                    "field": "@timestamp"
                  }
                },
                "min_timestamp": {
                  "min": {
                    "field": "@timestamp"
                  }
                }
              }
            }
          }
        }

        res = es.search(index=f"{index}", body=body)
        entries = []

        aggregations = res['aggregations']
        missing_host = aggregations['missing_host']
        if missing_host['doc_count'] != 0:
            # In Terraform case, there is no host
            start = pd.to_datetime(missing_host['min_timestamp']['value_as_string'])
            end = pd.to_datetime(missing_host['max_timestamp']['value_as_string'])
            host = None
            entries.append({"host": host, "start": start, "end": end })

        for entry in aggregations['hosts']['buckets']:
            start = pd.to_datetime(entry['min_timestamp']['value_as_string'])
            end = pd.to_datetime(entry['max_timestamp']['value_as_string'])
            host = entry['key']
            entries.append({"host": host, "start": start, "end": end })

        df = pd.DataFrame(entries)
        return df

    except Exception as e:
        logger.error(f"Error searching {program} logs: {e}")
        st.error(f"No {program} logs for {run_id}.")
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
          "terms": {
            "field": "host",
            "size": 10
          },
          "aggs": {
            "first_applied_message": {
              "filter": {
                "match": {
                  "message": "Applied"
                }
              },
              "aggs": {
                "first_message": {
                  "top_hits": {
                    "size": 1,
                    "sort": [{ "@timestamp": "asc" }]
                  }
                }
              }
            }
          }
        }
      }
    }

        res = es.search(index=f"{index}", body=body)
        entries = []
        for entry in res['aggregations']['hosts']['buckets']:
            source = entry['first_applied_message']['first_message']['hits']['hits'][0]['_source']
            message = source['message']
            host = source['host']
            match = re.search(PUPPET_DURATION_REGEX, message)
            if match:
                duration = float(match.group())
                delta = datetime.timedelta(seconds=duration)
                end = pd.to_datetime(source['@timestamp'])
                start = end - delta
                entries.append({"host": host, "start": start, "end": end})

        df = pd.DataFrame(entries)
        return df
    except Exception as e:
        logger.error(f"Error searching puppet logs: {e}")
        st.error(f"No puppet logs for {run_id}.")
        return pd.DataFrame()

def list_unique_values(es, index, key):
    try:
        query = {"size": 0, "aggs": {"unique_values": {"terms": {"field": key, "size": 1000}}}}
        res = es.search(index=index, body=query)
        unique_values = [bucket["key"] for bucket in res["aggregations"]["unique_values"]["buckets"]]
        return unique_values
    except Exception as e:
        logger.error(f"Error listing unique values: {e}")
        return []

def get_single_run(es, index, run_id):
    terraform_df = search_start_end(es, f"{index}", run_id, "terraform")
    terraform_df['program'] = "terraform"
    terraform_df['host'] = "terraform"
    cloudinit_df = search_start_end(es, f"{index}", run_id, "cloud-init")
    cloudinit_df['program'] = "cloudinit"
    puppet_df = search_puppet(es, INDEX, run_id)
    puppet_df['program'] = "puppet"

    workspace = get_workspace_from_run_id(es, index, run_id)

    df = pd.concat([terraform_df, puppet_df, cloudinit_df], ignore_index=True)
    df['run_id'] = run_id
    df['workspace'] = workspace
    return df

@st.cache_data
def get_all_run(_es, index, run_ids):
    dfs = []
    for run_id in run_ids:
        dfs.append(get_single_run(_es, index, run_id))
    df = pd.concat(dfs)

    df['duration_s'] = (df['end'] - df['start']).dt.total_seconds()
    return df

def main():
    st.title("MCSpeed Dashboard")

    with st.sidebar:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        host = st.text_input("Host")
        port = st.number_input("Port", value=443)

        if st.button("Connect"):
            es = connect_to_opensearch(username, password, host, port)
            if es:
                st.success("Connected to OpenSearch")
                st.session_state["es"] = es

    es = st.session_state.get("es")
    if es:
        run_ids = list_unique_values(es, INDEX, "run_id")
        df = get_all_run(es, INDEX, run_ids)

        workspaces = list_unique_values(es, INDEX, "workspace")
        workspaces_options = st.multiselect(
            'Clouds', workspaces, default=workspaces, format_func=lambda x : x.title())
        df = df[df['workspace'].isin(workspaces_options)]

        min_date = df['start'].min().to_pydatetime()
        max_date = df['end'].max().to_pydatetime()
        date_range = st.slider(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date, max_value=max_date)
        df = df[(df['start'] >= date_range[0]) & (df['end'] <= date_range[1])]


        program_duration = df.groupby(['run_id', 'program', 'workspace'])['duration_s'].max().reset_index()
        run_start = df.groupby(['run_id', 'workspace'])['start'].min().reset_index()
        result = pd.merge(program_duration, run_start, on=['run_id', 'workspace'])

        fig = px.bar(result, x='start', y='duration_s', color='program',
            barmode='stack', facet_col='workspace',
            category_orders={'program': ['terraform', 'cloudinit', 'puppet']},
            labels={
                "start": "Date",
                "duration_s": "Run duration (s)",
                "program": "Program"
             },
             hover_data=['run_id'],
        )
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1].title()))
        st.plotly_chart(fig)

        run_id = st.selectbox("Run IDs", df['run_id'].unique(), index=None)
        if run_id:
            df_single = df[df['run_id'] == run_id]

            if not df_single.empty:
                fig = px.timeline(df_single, x_start="start", x_end="end", y="host", color="program",
                     category_orders={'program': ['terraform', 'cloudinit', 'puppet']})

                fig.update_yaxes(autorange="reversed")
                st.plotly_chart(fig)

if __name__ == "__main__":
    main()
