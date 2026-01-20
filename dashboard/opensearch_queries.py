MAX_HOST_NB = 20

def build_terraform_query(run_id):
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"program.keyword": "terraform"}},
                    {"term": {"run_id.keyword": run_id}},
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
    }

def build_cloud_init_query(run_id):
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"program.keyword": "cloud-init"}},
                    {"term": {"run_id.keyword": run_id}},
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
    }

def build_puppet_query(run_id):
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"run_id.keyword": run_id}},
                    {"term": {"program.keyword": "puppet-agent"}},
                ]
            }
        },
        "aggs": {
            "hosts": {
                "terms": {"field": "host.keyword", "size": MAX_HOST_NB},
                "aggs": {
                    "first_applied_message": {
                        "filter": {"match_phrase": {"message": "Applied catalog in"}},
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
                        "filter": {
                            "bool": {
                                "must": [{"match": {"message": "failed"}}],
                                "must_not": [
                                    {"match_phrase": {"message": "Skipping because of failed dependencies"}},
                                    {"match_phrase": {"message": "Connection to https"}},
                                    {"match_phrase": {"message": "Failed to open TCP connection to"}},
                                ],
                            },
                        },
                        "aggs": {
                            "first_failure": {
                                "top_hits": {
                                    "size": 100,
                                    "sort": [{"@timestamp": "asc"}],
                                }
                            }
                        },
                    }
                },
            }
        },
    }

def build_run_ids_query(window):
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"lte": "now", "gt": f"now-{window}"}}},
                ]
            }
        },
        "aggs": {
            "unique_values": {
                "terms": {
                    "field": "run_id.keyword",
                    "size": 500,
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
