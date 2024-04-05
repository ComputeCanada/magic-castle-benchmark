#/bin/bash

FILENAME="./debug.txt"

# Remove color
cat $FILENAME | grep timestamp | sed -e 's/\x1b\[[0-9;]*m//g' > /tmp/log

while IFS= read -r line; do
    curl -X POST -u "${OPENSEARCH_USERNAME}:${OPENSEARCH_PASSWORD}" "${OPENSEARCH_URL}/${OPENSEARCH_INDEX}/_doc" -H 'Content-Type: application/json' -d "${line}"
done < <(jq -c "del(.hook) | del(.outputs) | . + { \"run_id\": \"${RUN_ID}\", \"program\":\"terraform\" }" /tmp/log)
