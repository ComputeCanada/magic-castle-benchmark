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

def search_cloudinit(es, index, run_id):
    try:
        # TODO: There is some issue with rsyslog and enforcing a proper mapping.
        # Once run_id is a keyword type and parsed_timestamp is a date type, we won't
        # need to iterate on all messages.
        # This is a simple workaround where we iterate in over all value to find the range.
        body = {
            "size": 10000,
            "query": {
                "bool": {
                    "must": [
                        {"match": {"run_id": run_id}},
                        {"match": {"program": "cloud-init"}},
                    ],
                }
            }
        }

        res = es.search(index=f"{index}_rsyslog", body=body)
        entries = []
        for entry in res['hits']['hits']:
            timestamp = pd.to_datetime(entry['_source']['parsed_timestamp'])
            host = entry['_source']['host']
            entries.append({"host": host, "timestamp": timestamp})

        df = pd.DataFrame(entries)
        df_start = df.loc[df.groupby("host")['timestamp'].idxmin()]
        df_end = df.loc[df.groupby("host")['timestamp'].idxmax()]
        merged_df = pd.merge(df_start, df_end, on='host', suffixes=('_start', '_end'))
        merged_df = merged_df.rename(columns={'timestamp_start': 'start', 'timestamp_end': 'end'})
        return merged_df
    except Exception as e:
        logger.error(f"Error searching cloud-init logs: {e}")
        st.error("Error searching cloud-init logs. Please try again.")
        return pd.DataFrame()

def search_puppet(es, index, run_id):
    try:
        body = {
            "size": 100,
            "query": {
                "bool": {
                    "must": [
                        {"match": {"run_id": run_id}},
                        {"match": {"program": "puppet-agent"}},
                        {"match_phrase": {"message": "Applied catalog"}}
                    ],
                }
            }
        }

        res = es.search(index=f"{index}_rsyslog", body=body)
        entries = []
        for entry in res['hits']['hits']:
            source = entry['_source']
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
        df = df.loc[df.groupby("host")['start'].idxmin()]
        return df
    except Exception as e:
        logger.error(f"Error searching puppet logs: {e}")
        st.error("Error searching puppet logs. Please try again.")
        return pd.DataFrame()

def search_terraform(es, index, run_id, message, type_):
    try:
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"run_id": run_id}},
                        {"match": {"program": "terraform"}},
                        {"match": {"type": type_}}
                    ],
                    "filter": {"match": {"@message": message}}
                }
            },
            "_source": ["@timestamp"]
        }

        res = es.search(index=index, body=body)
        return res
    except Exception as e:
        logger.error(f"Error searching Terraform logs: {e}")
        return None

def get_terraform_timestamp(es, index, run_id):
    try:
        res = search_terraform(es, index, run_id, "Apply complete", "change_summary")
        end = res['hits']['hits'][0]['_source']['@timestamp']
        res = search_terraform(es, index, run_id, "Terraform", "version")
        start = res['hits']['hits'][0]['_source']['@timestamp']
        return pd.to_datetime(start), pd.to_datetime(end)
    except Exception as e:
        logger.error(f"Error getting Terraform timestamps: {e}")
        return None, None

def list_unique_values(es, index, key):
    try:
        query = {"size": 0, "aggs": {"unique_values": {"terms": {"field": key}}}}
        res = es.search(index=index, body=query)
        unique_values = [bucket["key"] for bucket in res["aggregations"]["unique_values"]["buckets"]]
        return unique_values
    except Exception as e:
        logger.error(f"Error listing unique values: {e}")
        return []

def main():
    st.title("MCSpeed Dashboard")

    with st.sidebar:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        host = st.text_input("Host")
        port = st.number_input("Port", value=9200)

        if st.button("Connect"):
            es = connect_to_opensearch(username, password, host, port)
            if es:
                st.success("Connected to OpenSearch")
                st.session_state["es"] = es

    es = st.session_state.get("es")
    if es:
        run_ids = list_unique_values(es, INDEX, "run_id")
        run_id = st.selectbox("Run IDs", run_ids, index=None)
        if run_id:
            terraform_start, terraform_end = get_terraform_timestamp(es, INDEX, run_id)
            if terraform_start and terraform_end:
                terraform_df = pd.DataFrame([{"host": "terraform", "program": "terraform", "start": terraform_start, "end": terraform_end}])
                cloudinit_df = search_cloudinit(es, INDEX, run_id)
                cloudinit_df['program'] = "cloudinit"
                puppet_df = search_puppet(es, INDEX, run_id)
                puppet_df['program'] = "puppet"

                df = pd.concat([terraform_df, puppet_df, cloudinit_df], ignore_index=True)

                fig = px.timeline(df, x_start="start", x_end="end", y="host", color="program")
                fig.update_yaxes(autorange="reversed")
                st.plotly_chart(fig)

if __name__ == "__main__":
    main()
