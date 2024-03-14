#/bin/bash

FILENAME="./output.txt"

# Remove color
cat $FILENAME | grep timestamp | sed -e 's/\x1b\[[0-9;]*m//g' > /tmp/log

# Force mapping for run_id in case the index is new
curl -X PUT -u "${OPENSEARCH_USERNAME}:${OPENSEARCH_PASSWORD}" "${OPENSEARCH_URL}/${OPENSEARCH_INDEX}" -H 'Content-Type: application/json' -d '
{
  "mappings": {
    "properties":{
      "run_id":{ "type": "keyword" },
      "program":{ "type": "keyword" },
      "host":{ "type": "keyword" }
    }
  }
}
'

while IFS= read -r line; do
    curl -X POST -u "${OPENSEARCH_USERNAME}:${OPENSEARCH_PASSWORD}" "${OPENSEARCH_URL}/${OPENSEARCH_INDEX}/_doc" -H 'Content-Type: application/json' -d "${line}"
done < <(jq -c "del(.hook) | del(.outputs) | . + { \"run_id\": \"${RUN_ID}\", \"program\":\"terraform\" }" /tmp/log)
